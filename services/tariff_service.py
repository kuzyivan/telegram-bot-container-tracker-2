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
    __table_args__ = (Index('ix_tariff_stations_name_code', 'name', 'code'),)

class TariffMatrix(TariffBase):
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),)

class RailwaySection(TariffBase):
    __tablename__ = 'railway_sections'
    id: Mapped[int] = mapped_column(primary_key=True)
    node_start_code: Mapped[str | None] = mapped_column(String(6), index=True)
    node_end_code: Mapped[str | None] = mapped_column(String(6), index=True)
    source_file: Mapped[str | None] = mapped_column(String)
    stations_list: Mapped[list[dict]] = mapped_column(JSONB)
    __table_args__ = (Index('ix_stations_list_gin', 'stations_list', postgresql_using='gin'),)

class StationCoordinate(TariffBase):
    __tablename__ = 'station_coordinates'
    code: Mapped[str] = mapped_column(String(6), primary_key=True, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    name: Mapped[str | None] = mapped_column(String)

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
            transit_points.append({'code': parts[0], 'name': parts[1], 'distance': int(parts[2])})
        except Exception: continue
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
    tp_station = next((s for s in all_stations if s.operations and 'ТП' in s.operations), all_stations[0])

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
    
    stmt_ab = select(TariffMatrix.distance).where(TariffMatrix.station_a.ilike(f"{tp_a_clean}%"), TariffMatrix.station_b.ilike(f"{tp_b_clean}%")).limit(1)
    try:
        if (dist := (await session.execute(stmt_ab)).scalar_one_or_none()) is not None: return dist
        stmt_ba = select(TariffMatrix.distance).where(TariffMatrix.station_a.ilike(f"{tp_b_clean}%"), TariffMatrix.station_b.ilike(f"{tp_a_clean}%")).limit(1)
        return (await session.execute(stmt_ba)).scalar_one_or_none()
    except Exception: return None

# 🔥 НОВАЯ ФУНКЦИЯ: Обогащение координат
async def _enrich_path_with_coords(path_nodes: list[dict], session: AsyncSession) -> list[dict]:
    """
    Принимает список [{'code': '123', 'name': 'Name'}, ...]
    Возвращает список [{'name': 'Name', 'lat': 1.1, 'lon': 2.2}, ...]
    """
    if not path_nodes: return []
    
    # Собираем все коды
    codes = [node['code'] for node in path_nodes]
    # Добавляем 5-значные версии для поиска (в OSM часто 5 знаков)
    search_codes = set(codes)
    for c in codes:
        if len(c) == 6: search_codes.add(c[:-1])
    
    # Одним запросом достаем все координаты
    stmt = select(StationCoordinate).where(StationCoordinate.code.in_(search_codes))
    result = await session.execute(stmt)
    coords_map = {row.code: (row.lat, row.lon) for row in result.scalars()}
    
    enriched_path = []
    for node in path_nodes:
        code = node['code']
        lat_lon = coords_map.get(code)
        
        # Если не нашли по 6 знакам, ищем по 5
        if not lat_lon and len(code) == 6:
            lat_lon = coords_map.get(code[:-1])
            
        if lat_lon:
            enriched_path.append({
                'name': node['name'],
                'lat': lat_lon[0],
                'lon': lat_lon[1]
            })
        else:
            # Если координат нет, точку в маршрут для карты НЕ добавляем (чтобы не было 0,0)
            # Но можно добавить просто имя, если фронтенд умеет это обрабатывать.
            # Пока добавим только если есть координаты, чтобы линия была чистой.
            # Или добавим с lat=None, чтобы JS сам решил.
            enriched_path.append({'name': node['name'], 'lat': None, 'lon': None})
            
    return enriched_path


async def get_tariff_distance(from_station_name: str, to_station_name: str) -> dict | None:
    if not TariffSessionLocal: return None

    try:
        async with TariffSessionLocal() as session:
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)
            if not info_a or not info_b: return None
            
            # Совпадение
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {'distance': 0, 'info_a': info_a, 'info_b': info_b, 
                        'route_details': {'detailed_path': [], 'tpa_name': info_a['station_name']}}

            # ТП
            tps_a = info_a.get('transit_points') or [{'name': info_a['station_name'], 'code': info_a['station_code'], 'distance': 0}]
            tps_b = info_b.get('transit_points') or [{'name': info_b['station_name'], 'code': info_b['station_code'], 'distance': 0}]

            min_dist = float('inf')
            best = None 

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
                # 🔥 ИМПОРТ ГРАФА
                from services.railway_graph import railway_graph 
                
                full_path_nodes = [] # Список [{'code':..., 'name':...}]
                
                # 1. Start -> TP A
                tpa_code = best.get('tpa_code') or info_b['station_code']
                seg1 = railway_graph.get_shortest_path_detailed(info_a['station_code'], tpa_code)
                if seg1: full_path_nodes.extend(seg1)
                else: full_path_nodes.append({'code': info_a['station_code'], 'name': info_a['station_name']})

                # 2. TP A -> TP B
                tpb_code = best.get('tpb_code')
                if tpa_code and tpb_code and tpa_code != tpb_code:
                    seg2 = railway_graph.get_shortest_path_detailed(tpa_code, tpb_code)
                    if seg2: full_path_nodes.extend(seg2[1:]) # Skip first duplicate

                # 3. TP B -> End
                if tpb_code and tpb_code != info_b['station_code']:
                    seg3 = railway_graph.get_shortest_path_detailed(tpb_code, info_b['station_code'])
                    if seg3: full_path_nodes.extend(seg3[1:])
                
                # Очистка дублей
                clean_nodes = []
                seen_codes = set()
                # Для сохранения порядка, но без дублей подряд
                for node in full_path_nodes:
                    if not clean_nodes or clean_nodes[-1]['code'] != node['code']:
                        clean_nodes.append(node)

                # 🔥 ОБОГАЩЕНИЕ КООРДИНАТАМИ
                detailed_path_with_coords = await _enrich_path_with_coords(clean_nodes, session)
                
                # Сохраняем в результат
                # detailed_path_coords - для карты (объекты)
                # detailed_path - для текста (строки)
                best['detailed_path_coords'] = [p for p in detailed_path_with_coords if p['lat'] is not None]
                best['detailed_path'] = [node['name'] for node in clean_nodes] # Для текстового списка

                logger.info(f"✅ Маршрут: {len(clean_nodes)} станций, из них с координатами: {len(best['detailed_path_coords'])}")
                
                return {'distance': int(min_dist), 'info_a': info_a, 'info_b': info_b, 'route_details': best}

            return None

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return None

async def find_stations_by_name(station_name: str) -> list[dict]:
    if not TariffSessionLocal: return []
    cleaned = _normalize_station_name_for_db(station_name)
    async with TariffSessionLocal() as session:
        stmt = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned}%")).limit(10)
        res = await session.execute(stmt)
        return [{'name': s.name, 'code': s.code, 'railway': s.railway} for s in res.scalars()]
