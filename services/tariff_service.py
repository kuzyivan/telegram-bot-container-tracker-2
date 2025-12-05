# services/tariff_service.py
import asyncio
import re
import logging
from sqlalchemy import select, ARRAY, exc, func, Index, UniqueConstraint, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from sqlalchemy.types import Float
from sqlalchemy.dialects.postgresql import JSONB

# Импорт сессии
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
    """Хранит последовательность станций участка (из Книги 1) для построения Графа."""
    __tablename__ = 'railway_sections'
    id: Mapped[int] = mapped_column(primary_key=True)
    node_start_code: Mapped[str | None] = mapped_column(String(6), index=True)
    node_end_code: Mapped[str | None] = mapped_column(String(6), index=True)
    source_file: Mapped[str | None] = mapped_column(String)
    stations_list: Mapped[list[dict]] = mapped_column(JSONB)
    
    __table_args__ = (
        Index('ix_stations_list_gin', 'stations_list', postgresql_using='gin'),
    )

class StationCoordinate(TariffBase):
    """Кэш координат станций по коду ЕСР (из OSM)."""
    __tablename__ = 'station_coordinates'
    code: Mapped[str] = mapped_column(String(6), primary_key=True, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    name: Mapped[str | None] = mapped_column(String)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _normalize_station_name_for_db(name: str) -> str:
    """Убирает лишние скобки в конце и нормализует пробелы перед цифрами."""
    if not name: return ""
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    cleaned_name = re.sub(r'([А-ЯЁA-Z])(\d)', r'\1 \2', cleaned_name)
    return cleaned_name if cleaned_name else name.strip()

def _parse_transit_points_from_db(tp_strings: list[str]) -> list[dict]:
    """Парсит строку вида 'CODE:NAME:DISTANCE'."""
    transit_points = []
    if not tp_strings: return []
    for tp_str in tp_strings:
        try:
            parts = tp_str.split(':')
            if len(parts) >= 3:
                transit_points.append({
                    'code': parts[0], 
                    'name': parts[1], 
                    'distance': int(parts[2])
                })
        except Exception:
            continue
    return transit_points

async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    """
    Ищет станцию в БД для калькулятора.
    Умеет обрабатывать префиксы 'РАЗЪЕЗД', 'СТАНЦИЯ' и т.д.
    """
    # 1. Базовая очистка
    cleaned_name = _normalize_station_name_for_db(station_name)
    search_candidates = [cleaned_name]
    
    # 2. Очистка от слов-паразитов (Разъезд, ОП, Ст.)
    prefixes_to_remove = [
        "РАЗЪЕЗД", "РЗД", "Р-Д", 
        "СТАНЦИЯ", "СТ.", "СТ ", 
        "ОП", "О.П.", "О.П", "БП", "П/П"
    ]
    
    upper_name = cleaned_name.upper()
    for prefix in prefixes_to_remove:
        # Если начинается с префикса (например "РАЗЪЕЗД УСКОЛЬ")
        if upper_name.startswith(prefix + " ") or upper_name.startswith(prefix + "."):
            stripped = cleaned_name[len(prefix):].strip(" .")
            if stripped:
                search_candidates.append(stripped)
            break 
            
    # 3. Поиск по кандидатам
    all_stations = []
    for candidate in search_candidates:
        # Варианты написания (с римскими цифрами)
        search_variants = {candidate}
        if " 2" in candidate: search_variants.add(candidate.replace(" 2", " II"))
        if " 1" in candidate: search_variants.add(candidate.replace(" 1", " I"))
        
        search_variants_lower = [v.lower() for v in search_variants]
        
        # А) Точное совпадение
        stmt = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
        result = await session.execute(stmt)
        found = result.scalars().all()
        
        if found:
            all_stations = found
            break # Нашли - выходим
            
        # Б) Поиск "Начинается с..." (например, ищем 'Усколь', а в базе 'Усколь (рзд)')
        stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{candidate}%"))
        result_fallback = await session.execute(stmt_startswith)
        found_fallback = result_fallback.scalars().all()
        
        if found_fallback:
            all_stations = found_fallback
            break

    if not all_stations:
        return None 

    # 4. Выбор лучшей станции (если нашли несколько)
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
    """Получает расстояние между транзитными пунктами из матрицы."""
    tp_a_clean = tp_a_name.split(' (')[0].strip()
    tp_b_clean = tp_b_name.split(' (')[0].strip()
    
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_a_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_b_clean}%")
    ).limit(1)
    
    try:
        dist = (await session.execute(stmt_ab)).scalar_one_or_none()
        if dist is not None: return dist
        
        stmt_ba = select(TariffMatrix.distance).where(
            TariffMatrix.station_a.ilike(f"{tp_b_clean}%"),
            TariffMatrix.station_b.ilike(f"{tp_a_clean}%")
        ).limit(1)
        return (await session.execute(stmt_ba)).scalar_one_or_none()
    except Exception:
        return None

async def _enrich_path_with_coords(path_nodes: list[dict], session: AsyncSession) -> list[dict]:
    """
    Добавляет координаты (lat, lon) к списку станций, используя таблицу station_coordinates.
    """
    if not path_nodes: return []
    
    codes = [node['code'] for node in path_nodes]
    # Добавляем 5-значные версии кодов для поиска (в OSM часто 5 знаков)
    search_codes = set(codes)
    for c in codes:
        if len(c) == 6: search_codes.add(c[:-1])
    
    stmt = select(StationCoordinate).where(StationCoordinate.code.in_(search_codes))
    result = await session.execute(stmt)
    coords_map = {row.code: (row.lat, row.lon) for row in result.scalars()}
    
    enriched_path = []
    for node in path_nodes:
        code = node['code']
        lat_lon = coords_map.get(code)
        
        if not lat_lon and len(code) == 6:
            lat_lon = coords_map.get(code[:-1])
            
        if lat_lon:
            enriched_path.append({
                'name': node['name'],
                'lat': lat_lon[0],
                'lon': lat_lon[1]
            })
        else:
            enriched_path.append({'name': node['name'], 'lat': None, 'lon': None})
            
    return enriched_path

# --- ГЛАВНАЯ ФУНКЦИЯ РАСЧЕТА ---

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> dict | None:
    if not TariffSessionLocal: 
        logger.error("TARIFF_DATABASE_URL не настроен")
        return None

    try:
        async with TariffSessionLocal() as session:
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)
            
            if not info_a or not info_b: return None
            
            # Совпадение станций
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {
                    'distance': 0, 'info_a': info_a, 'info_b': info_b, 
                    'route_details': {'detailed_path': [], 'detailed_path_coords': [], 'tpa_name': info_a['station_name']}
                }

            # Определение ТП (Транзитных Пунктов)
            tps_a = info_a.get('transit_points') or [{'name': info_a['station_name'], 'code': info_a['station_code'], 'distance': 0}]
            tps_b = info_b.get('transit_points') or [{'name': info_b['station_name'], 'code': info_b['station_code'], 'distance': 0}]

            min_dist = float('inf')
            best = None 

            # Перебор вариантов маршрута через ТП
            for tp_a in tps_a:
                for tp_b in tps_b:
                    current_dist = None
                    transit_val = 0
                    
                    if tp_a['name'] == tp_b['name']:
                        current_dist = tp_a['distance'] + tp_b['distance']
                    else:
                        td = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                        if td is not None:
                            current_dist = tp_a['distance'] + td + tp_b['distance']
                            transit_val = td
                            
                    if current_dist is not None and current_dist < min_dist:
                        min_dist = current_dist
                        best = {
                            'tpa_name': tp_a['name'], 'tpa_code': tp_a['code'], 'distance_a_to_tpa': tp_a['distance'],
                            'tpb_name': tp_b['name'], 'tpb_code': tp_b['code'], 'distance_tpb_to_b': tp_b['distance'],
                            'distance_tpa_to_tpb': transit_val
                        }

            if best:
                # 🔥 ИМПОРТ ГРАФА ВНУТРИ ФУНКЦИИ (чтобы избежать circular import)
                from services.railway_graph import railway_graph 
                
                full_path_nodes = [] # Список [{'code':..., 'name':...}]
                
                # 1. Сегмент: Старт -> ТП А
                tpa_code = best.get('tpa_code') or info_b['station_code']
                seg1 = railway_graph.get_shortest_path_detailed(info_a['station_code'], tpa_code)
                
                if seg1: 
                    full_path_nodes.extend(seg1)
                else: 
                    full_path_nodes.append({'code': info_a['station_code'], 'name': info_a['station_name']})

                # 2. Сегмент: ТП А -> ТП Б (Магистраль)
                tpb_code = best.get('tpb_code')
                if tpa_code and tpb_code and tpa_code != tpb_code:
                    seg2 = railway_graph.get_shortest_path_detailed(tpa_code, tpb_code)
                    if seg2: 
                        full_path_nodes.extend(seg2[1:]) # Пропускаем первый дубликат

                # 3. Сегмент: ТП Б -> Конец
                if tpb_code and tpb_code != info_b['station_code']:
                    seg3 = railway_graph.get_shortest_path_detailed(tpb_code, info_b['station_code'])
                    if seg3: 
                        full_path_nodes.extend(seg3[1:])
                
                # Очистка дублей подряд
                clean_nodes = []
                for node in full_path_nodes:
                    if not clean_nodes or clean_nodes[-1]['code'] != node['code']:
                        clean_nodes.append(node)

                # 🔥 ОБОГАЩЕНИЕ КООРДИНАТАМИ
                detailed_path_with_coords = await _enrich_path_with_coords(clean_nodes, session)
                
                # Сохраняем в результат
                best['detailed_path_coords'] = [p for p in detailed_path_with_coords if p['lat'] is not None]
                best['detailed_path'] = [node['name'] for node in clean_nodes]

                logger.info(f"✅ Маршрут построен: {len(clean_nodes)} станций, с координатами: {len(best['detailed_path_coords'])}")
                
                return {
                    'distance': int(min_dist), 
                    'info_a': info_a, 
                    'info_b': info_b, 
                    'route_details': best
                }

            return None

    except Exception as e:
        logger.error(f"Error in tariff calc: {e}", exc_info=True)
        return None

async def find_stations_by_name(station_name: str) -> list[dict]:
    """
    Автодополнение для поиска станций (для Бота и Веба).
    Умеет обрабатывать префиксы 'РАЗЪЕЗД', 'СТАНЦИЯ' и т.д.
    """
    if not TariffSessionLocal: return []
    
    # 1. Базовая очистка
    cleaned_name = _normalize_station_name_for_db(station_name)
    search_candidates = [cleaned_name]
    
    # 2. Очистка от слов-паразитов
    prefixes_to_remove = [
        "РАЗЪЕЗД", "РЗД", "Р-Д", 
        "СТАНЦИЯ", "СТ.", "СТ ", 
        "ОП", "О.П.", "О.П", "БП", "П/П"
    ]
    
    upper_name = cleaned_name.upper()
    for prefix in prefixes_to_remove:
        if upper_name.startswith(prefix + " ") or upper_name.startswith(prefix + "."):
            stripped = cleaned_name[len(prefix):].strip(" .")
            if stripped:
                search_candidates.append(stripped)
            break 

    async with TariffSessionLocal() as session:
        for candidate in search_candidates:
            # Ищем совпадения "Начинается с..."
            stmt = select(TariffStation).where(TariffStation.name.ilike(f"{candidate}%")).limit(10)
            res = await session.execute(stmt)
            stations = res.scalars().all()
            
            if stations:
                return [{'name': s.name, 'code': s.code, 'railway': s.railway} for s in stations]
        
        return []