# services/tariff_service.py
import asyncio
import re
import logging
from sqlalchemy import select, ARRAY, exc, func, Index, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from sqlalchemy.dialects.postgresql import JSONB

# --- Импорты сессии ---
from db import TariffSessionLocal

logger = logging.getLogger(__name__)

# --- Определение Base ---
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
    """
    Хранит последовательность станций участка (из Книги 1).
    """
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
    # Вставляем пробел между буквой и цифрой (ТОМСК1 -> ТОМСК 1)
    cleaned_name = re.sub(r'([А-ЯЁA-Z])(\d)', r'\1 \2', cleaned_name)
    return cleaned_name if cleaned_name else name.strip()

def _parse_transit_points_from_db(tp_strings: list[str]) -> list[dict]:
    transit_points = []
    if not tp_strings:
        return []
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
    if " 2" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 1", " I"))
    
    search_variants_lower = [v.lower() for v in search_variants]
    
    stmt = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
    result = await session.execute(stmt)
    all_stations = result.scalars().all()

    if not all_stations:
        stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
        result_fallback = await session.execute(stmt_startswith)
        all_stations = result_fallback.scalars().all()

    if not all_stations:
        return None 

    tp_station = None
    for station in all_stations:
        if station.operations and 'ТП' in station.operations:
            tp_station = station
            break 
    
    if not tp_station:
        tp_station = all_stations[0]

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
    
    stmt_ba = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_b_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_a_clean}%")
    ).limit(1)

    try:
        result_ab = await session.execute(stmt_ab)
        distance = result_ab.scalar_one_or_none()
        if distance is not None: return distance

        result_ba = await session.execute(stmt_ba)
        distance_ba = result_ba.scalar_one_or_none()
        if distance_ba is not None: return distance_ba
            
    except exc.OperationalError as e:
        logger.error(f"Ошибка подключения к БД тарифов: {e}")
        return None
    return None

# --- 🆕 ПОИСК ДЕТАЛЬНОГО МАРШРУТА (Книга 1) ---

async def _find_stations_between(code_a: str, code_b: str, session: AsyncSession) -> list[dict]:
    """
    Ищет в railway_sections сегмент, содержащий оба кода станций.
    """
    if code_a == code_b:
        return []

    # ✅ ИСПРАВЛЕНО: Используем CAST(... AS jsonb) вместо ::jsonb, чтобы избежать ошибки парсинга
    sql = text("""
        SELECT stations_list 
        FROM railway_sections 
        WHERE stations_list @> CAST(:json_a AS jsonb) 
          AND stations_list @> CAST(:json_b AS jsonb)
        LIMIT 1
    """)
    
    json_a = f'[{{"c": "{code_a}"}}]'
    json_b = f'[{{"c": "{code_b}"}}]'
    
    try:
        result = await session.execute(sql, {"json_a": json_a, "json_b": json_b})
        row = result.scalar_one_or_none()
        
        if row:
            full_list = row # Список словарей [{'c':..., 'n':...}]
            
            idx_a = -1
            idx_b = -1
            
            for i, st in enumerate(full_list):
                if st['c'] == code_a: idx_a = i
                if st['c'] == code_b: idx_b = i
            
            if idx_a != -1 and idx_b != -1:
                # Если A раньше B -> прямой порядок
                if idx_a < idx_b:
                    return full_list[idx_a : idx_b+1]
                # Если B раньше A -> обратный порядок (разворачиваем)
                else:
                    segment = full_list[idx_b : idx_a+1]
                    return segment[::-1]
                    
    except Exception as e:
        logger.error(f"Ошибка поиска детального маршрута для {code_a}-{code_b}: {e}")
        
    return []

# --- ГЛАВНАЯ ФУНКЦИЯ РАСЧЕТА ---

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> dict | None:
    if not TariffSessionLocal:
        logger.error("[Tariff] TARIFF_DATABASE_URL не настроен.")
        return None

    try:
        async with TariffSessionLocal() as session:
            
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)

            if not info_a or not info_b:
                return None
            
            logger.info(f"[Tariff Debug] A Info: Name={info_a.get('station_name')}, TPs={len(info_a.get('transit_points', []))}")
            logger.info(f"[Tariff Debug] B Info: Name={info_b.get('station_name')}, TPs={len(info_b.get('transit_points', []))}")
            
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {'distance': 0, 'info_a': info_a, 'info_b': info_b, 'route_details': {'tpa_name': info_a['station_name'], 'tpb_name': info_a['station_name'], 'distance_a_to_tpa': 0, 'distance_tpa_to_tpb': 0, 'distance_tpb_to_b': 0, 'detailed_path': [info_a['station_name']]}}

            # --- Определение ТП ---
            tps_a = info_a.get('transit_points', [])
            operations_a = info_a.get('operations') or ""
            # Добавляем саму станцию как ТП, если у неё нет ТП или она сама ТП
            if not tps_a or ('ТП' in operations_a and not tps_a):
                 tps_a = [{'name': info_a['station_name'], 'code': info_a['station_code'], 'distance': 0}]
            
            tps_b = info_b.get('transit_points', [])
            operations_b = info_b.get('operations') or ""
            if not tps_b or ('ТП' in operations_b and not tps_b):
                tps_b = [{'name': info_b['station_name'], 'code': info_b['station_code'], 'distance': 0}]

            min_total_distance = float('inf')
            best_route = None 
            route_found = False

            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    # Если ТП совпадают
                    if tp_a['name'] == tp_b['name']:
                        current_dist = tp_a['distance'] + tp_b['distance']
                        if current_dist < min_total_distance:
                            min_total_distance = current_dist
                            route_found = True
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'],
                                'tpa_name': tp_a['name'],
                                'tpa_code': tp_a['code'], # ✅ Сохраняем код для поиска пути
                                'distance_tpa_to_tpb': 0, 
                                'tpb_name': tp_b['name'],
                                'tpb_code': tp_b['code'], # ✅ Сохраняем код для поиска пути
                                'distance_tpb_to_b': tp_b['distance'],
                            }
                        continue 
                        
                    # Ищем в матрице
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    
                    if transit_dist is not None:
                        total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
                        
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            route_found = True
                            
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'],
                                'tpa_name': tp_a['name'],
                                'tpa_code': tp_a['code'], # ✅ Важно
                                'distance_tpa_to_tpb': transit_dist,
                                'tpb_name': tp_b['name'],
                                'tpb_code': tp_b['code'], # ✅ Важно
                                'distance_tpb_to_b': tp_b['distance'],
                            }

            if route_found and best_route is not None:
                distance_int = int(min_total_distance)
                
                # --- 🔥 СБОРКА ДЕТАЛЬНОГО МАРШРУТА ---
                full_path_names = []
                
                # 1. Сегмент: Старт -> ТП А
                # Ищем путь от начальной станции до первого ТП (если это разные станции)
                code_start = info_a['station_code']
                code_tpa = best_route['tpa_code']
                
                segment_1 = await _find_stations_between(code_start, code_tpa, session)
                if segment_1:
                    full_path_names.extend([s['n'] for s in segment_1])
                else:
                    full_path_names.append(info_a['station_name'])
                    if best_route['tpa_name'] != info_a['station_name']:
                        full_path_names.append(best_route['tpa_name'])

                # 2. Сегмент: ТП А -> ТП Б (Магистраль)
                # Это самый сложный участок (междорожный). 
                # Книга 1 редко содержит длинные маршруты между дорогами.
                # Поэтому здесь мы просто оставляем прямую линию между ТП, 
                # либо пытаемся найти, если повезет.
                code_tpb = best_route['tpb_code']
                
                if code_tpa != code_tpb:
                    # Пробуем найти, вдруг это один участок
                    segment_2 = await _find_stations_between(code_tpa, code_tpb, session)
                    if segment_2:
                        # Пропускаем первый элемент, так как он дублирует конец предыдущего
                        full_path_names.extend([s['n'] for s in segment_2[1:]])
                    else:
                        # Если не нашли, просто добавляем точку ТП Б
                        full_path_names.append(best_route['tpb_name'])

                # 3. Сегмент: ТП Б -> Конец
                code_end = info_b['station_code']
                segment_3 = await _find_stations_between(code_tpb, code_end, session)
                
                if segment_3:
                    # Пропускаем первый элемент (дубль ТП Б)
                    for s in segment_3:
                        if s['n'] not in full_path_names: # Избегаем дублей имен подряд
                            full_path_names.append(s['n'])
                else:
                    if info_b['station_name'] not in full_path_names:
                        full_path_names.append(info_b['station_name'])

                # Очистка дубликатов подряд (на всякий случай)
                clean_path = []
                for name in full_path_names:
                    if not clean_path or clean_path[-1] != name:
                        clean_path.append(name)

                best_route['detailed_path'] = clean_path
                
                logger.info(f"✅ [Tariff] Маршрут построен: {len(clean_path)} точек.")
                
                return {
                    'distance': distance_int,
                    'info_a': info_a,
                    'info_b': info_b,
                    'route_details': best_route 
                }
            else:
                logger.info(f"[Tariff] Маршрут не найден в матрице.")
                return None

    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при расчете: {e}", exc_info=True)
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
