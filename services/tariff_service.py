# services/tariff_service.py
import asyncio
import re
import logging
from sqlalchemy import select, ARRAY, exc, func, Index, UniqueConstraint, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from sqlalchemy.dialects.postgresql import JSONB

# --- Импорты сессии ---
from db import TariffSessionLocal

logger = logging.getLogger(__name__)

class TariffBase(DeclarativeBase):
    pass

# --- МОДЕЛИ ---

class TariffStation(TariffBase):
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True)
    railway: Mapped[str | None] = mapped_column(String)
    operations: Mapped[str | None] = mapped_column(String)
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    __table_args__ = (
        Index('ix_tariff_stations_name_code', 'name', 'code'),
    )

class TariffMatrix(TariffBase):
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )

class RailwaySection(TariffBase):
    __tablename__ = 'railway_sections'
    id: Mapped[int] = mapped_column(primary_key=True)
    node_start_code: Mapped[str | None] = mapped_column(String(6), index=True)
    node_end_code: Mapped[str | None] = mapped_column(String(6), index=True)
    source_file: Mapped[str | None] = mapped_column(String)
    stations_list: Mapped[list[dict]] = mapped_column(JSONB)

    __table_args__ = (
        Index('ix_stations_list_gin', 'stations_list', postgresql_using='gin'),
    )

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _normalize_station_name_for_db(name: str) -> str:
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    cleaned_name = re.sub(r'([А-ЯЁA-Z])(\d)', r'\1 \2', cleaned_name)
    return cleaned_name if cleaned_name else name.strip()

def _parse_transit_points_from_db(tp_strings: list[str]) -> list[dict]:
    transit_points = []
    if not tp_strings: return []
    for tp_str in tp_strings:
        try:
            parts = tp_str.split(':')
            transit_points.append({
                'code': parts[0],
                'name': parts[1],
                'distance': int(parts[2])
            })
        except Exception:
            continue
    return transit_points

async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    cleaned_name = _normalize_station_name_for_db(station_name)
    search_variants = {cleaned_name}
    if " 2" in cleaned_name: search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name: search_variants.add(cleaned_name.replace(" 1", " I"))
    
    search_variants_lower = [v.lower() for v in search_variants]
    stmt = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
    result = await session.execute(stmt)
    all_stations = result.scalars().all()

    if not all_stations:
        stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
        result_fallback = await session.execute(stmt_startswith)
        all_stations = result_fallback.scalars().all()

    if not all_stations: return None 

    tp_station = None
    for station in all_stations:
        if station.operations and 'ТП' in station.operations:
            tp_station = station
            break 
    if not tp_station: tp_station = all_stations[0]

    return {
        'station_name': tp_station.name,
        'station_code': tp_station.code,
        'operations': tp_station.operations,
        'railway': tp_station.railway, 
        'transit_points': _parse_transit_points_from_db(tp_station.transit_points or [])
    }

async def _get_matrix_distance_from_db(tp_a_name: str, tp_b_name: str, session: AsyncSession) -> int | None:
    tp_a_clean = tp_a_name.split(' (')[0].strip()
    tp_b_clean = tp_b_name.split(' (')[0].strip()
    
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_a_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_b_clean}%")
    ).limit(1)
    
    try:
        result_ab = await session.execute(stmt_ab)
        distance = result_ab.scalar_one_or_none()
        if distance is not None: return distance

        stmt_ba = select(TariffMatrix.distance).where(
            TariffMatrix.station_a.ilike(f"{tp_b_clean}%"),
            TariffMatrix.station_b.ilike(f"{tp_a_clean}%")
        ).limit(1)
        
        result_ba = await session.execute(stmt_ba)
        return result_ba.scalar_one_or_none()
            
    except Exception as e:
        logger.error(f"Ошибка БД (Матрица): {e}")
        return None

# --- 🆕 "УМНЫЙ" ПОИСК МАРШРУТА ---

async def _find_stations_between(code_a: str, code_b: str, session: AsyncSession) -> list[dict]:
    """
    Ищет сегмент. Пробует точный код (6 знаков) и короткий (5 знаков).
    """
    if code_a == code_b: return []

    # Генерация вариантов кодов (6 цифр и 5 цифр)
    # Если код 123456 -> пробуем 123456 и 12345
    # Если код 12345 -> пробуем 12345
    variants_a = [code_a]
    if len(code_a) == 6: variants_a.append(code_a[:-1])
    
    variants_b = [code_b]
    if len(code_b) == 6: variants_b.append(code_b[:-1])

    logger.info(f"🔎 Поиск участка {code_a} -> {code_b}. Варианты A: {variants_a}, B: {variants_b}")

    # Строим SQL с OR условиями для JSON
    # Нам нужно найти строку, где (stations_list содержит A1 ИЛИ A2) И (stations_list содержит B1 ИЛИ B2)
    
    # Чтобы не усложнять SQL, сделаем цикл по вариантам (их всего 1-2, это быстро)
    for ca in variants_a:
        for cb in variants_b:
            sql = text("""
                SELECT stations_list 
                FROM railway_sections 
                WHERE stations_list @> CAST(:json_a AS jsonb) 
                  AND stations_list @> CAST(:json_b AS jsonb)
                LIMIT 1
            """)
            
            json_a = f'[{{"c": "{ca}"}}]'
            json_b = f'[{{"c": "{cb}"}}]'
            
            try:
                result = await session.execute(sql, {"json_a": json_a, "json_b": json_b})
                row = result.scalar_one_or_none()
                
                if row:
                    logger.info(f"   ✅ Найдено совпадение по паре {ca}-{cb}!")
                    full_list = row 
                    
                    idx_a = -1
                    idx_b = -1
                    
                    for i, st in enumerate(full_list):
                        if st['c'] == ca: idx_a = i
                        if st['c'] == cb: idx_b = i
                    
                    if idx_a != -1 and idx_b != -1:
                        if idx_a < idx_b:
                            return full_list[idx_a : idx_b+1]
                        else:
                            segment = full_list[idx_b : idx_a+1]
                            return segment[::-1]
            except Exception as e:
                logger.error(f"SQL Error: {e}")

    logger.warning(f"   ❌ Участок {code_a}-{code_b} не найден в Книге 1.")
    return []

# --- ГЛАВНАЯ ФУНКЦИЯ ---

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> dict | None:
    if not TariffSessionLocal: return None

    try:
        async with TariffSessionLocal() as session:
            
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)

            if not info_a or not info_b: return None
            
            # Совпадение станций
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {
                    'distance': 0, 'info_a': info_a, 'info_b': info_b, 
                    'route_details': {'tpa_name': info_a['station_name'], 'tpb_name': info_a['station_name'], 'detailed_path': [info_a['station_name']]}
                }

            # ТП
            tps_a = info_a.get('transit_points') or [{'name': info_a['station_name'], 'code': info_a['station_code'], 'distance': 0}]
            tps_b = info_b.get('transit_points') or [{'name': info_b['station_name'], 'code': info_b['station_code'], 'distance': 0}]

            min_total_distance = float('inf')
            best_route = None 

            for tp_a in tps_a:
                for tp_b in tps_b:
                    # 1. ТП совпадают
                    if tp_a['name'] == tp_b['name']:
                        dist = tp_a['distance'] + tp_b['distance']
                        if dist < min_total_distance:
                            min_total_distance = dist
                            best_route = {
                                'tpa_name': tp_a['name'], 'tpa_code': tp_a['code'], 'distance_a_to_tpa': tp_a['distance'],
                                'tpb_name': tp_b['name'], 'tpb_code': tp_b['code'], 'distance_tpb_to_b': tp_b['distance'],
                                'distance_tpa_to_tpb': 0
                            }
                        continue 
                        
                    # 2. Матрица
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    if transit_dist is not None:
                        total = tp_a['distance'] + transit_dist + tp_b['distance']
                        if total < min_total_distance:
                            min_total_distance = total
                            best_route = {
                                'tpa_name': tp_a['name'], 'tpa_code': tp_a['code'], 'distance_a_to_tpa': tp_a['distance'],
                                'tpb_name': tp_b['name'], 'tpb_code': tp_b['code'], 'distance_tpb_to_b': tp_b['distance'],
                                'distance_tpa_to_tpb': transit_dist
                            }

            if best_route:
                distance_int = int(min_total_distance)
                
                # === 🔥 ИМПОРТ ПЕРЕНЕСЕН СЮДА (Разрыв цикла) ===
                from services.railway_graph import railway_graph 
                # ===============================================

                # === 🔥 НОВАЯ ЛОГИКА ПОСТРОЕНИЯ ПУТИ ЧЕРЕЗ ГРАФ ===
                full_path_names = []
                
                # У нас есть ключевые точки маршрута: Start -> (TP_A -> TP_B) -> End
                
                # 1. Путь: Start -> TP_A (или сразу End, если нет ТП)
                tpa_code = best_route.get('tpa_code') or info_b['station_code']
                
                path_segment_1 = railway_graph.get_shortest_path(info_a['station_code'], tpa_code)
                
                if path_segment_1:
                    full_path_names.extend(path_segment_1)
                else:
                    full_path_names.append(info_a['station_name'])

                # 2. Путь: TP_A -> TP_B (если они разные)
                tpb_code = best_route.get('tpb_code')
                if tpa_code and tpb_code and tpa_code != tpb_code:
                    path_segment_2 = railway_graph.get_shortest_path(tpa_code, tpb_code)
                    if path_segment_2:
                        # Исключаем первый элемент, чтобы не дублировать (он = tpa)
                        full_path_names.extend(path_segment_2[1:])
                
                # 3. Путь: TP_B -> End
                if tpb_code and tpb_code != info_b['station_code']:
                    path_segment_3 = railway_graph.get_shortest_path(tpb_code, info_b['station_code'])
                    if path_segment_3:
                        full_path_names.extend(path_segment_3[1:])
                
                # Финальная очистка от дублей имен подряд
                clean_path = []
                for name in full_path_names:
                    if not clean_path or clean_path[-1] != name:
                        clean_path.append(name)
                
                # Если граф не нашел путь (разрыв в данных), вставляем хотя бы ключевые точки
                if len(clean_path) < 2:
                    clean_path = [
                        info_a['station_name'], 
                        best_route.get('tpa_name'), 
                        best_route.get('tpb_name'), 
                        info_b['station_name']
                    ]
                    # Убираем None и дубли
                    clean_path = list(dict.fromkeys([x for x in clean_path if x]))

                best_route['detailed_path'] = clean_path
                logger.info(f"✅ [Graph] Маршрут построен: {len(clean_path)} станций.")
                
                return {
                    'distance': distance_int,
                    'info_a': info_a,
                    'info_b': info_b,
                    'route_details': best_route 
                }

            return None

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return None

async def find_stations_by_name(station_name: str) -> list[dict]:
    if not TariffSessionLocal: return []
    cleaned_name = _normalize_station_name_for_db(station_name)
    search_variants = {cleaned_name}
    if " 2" in cleaned_name: search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name: search_variants.add(cleaned_name.replace(" 1", " I"))

    async with TariffSessionLocal() as session:
        search_variants_lower = [v.lower() for v in search_variants]
        stmt_exact = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
        result_exact = await session.execute(stmt_exact)
        all_stations = result_exact.scalars().all()
        
        if not all_stations:
            stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
            result_startswith = await session.execute(stmt_startswith)
            all_stations = result_startswith.scalars().all()

        return [{'name': s.name, 'code': s.code, 'railway': s.railway} for s in all_stations]