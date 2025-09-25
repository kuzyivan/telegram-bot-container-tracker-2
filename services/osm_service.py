# services/osm_service.py
import overpass
import asyncio
import re
from geopy.distance import geodesic
from logger import get_logger
from db import SessionLocal
from models import RailwayStation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)
api = overpass.API(timeout=90)

def _clean_station_name(station_name: str) -> str:
    """Убирает код станции в скобках, например, 'СЕЛЯТИНО (181102)' -> 'СЕЛЯТИНО'."""
    return re.sub(r'\s*\(\d+\)$', '', station_name).strip()

async def get_station_from_cache(name: str) -> RailwayStation | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(RailwayStation).where(RailwayStation.name == name.upper())
        )
        return result.scalar_one_or_none()

async def save_station_to_cache(name: str, lat: float, lon: float):
    async with SessionLocal() as session:
        stmt = pg_insert(RailwayStation).values(
            name=name.upper(), latitude=lat, longitude=lon
        ).on_conflict_do_nothing(index_elements=['name'])
        await session.execute(stmt)
        await session.commit()

async def fetch_station_coords(station_name: str) -> dict | None:
    clean_name = _clean_station_name(station_name)
    cached_station = await get_station_from_cache(clean_name)
    if cached_station:
        logger.info(f"Станция '{clean_name}' найдена в кеше.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    logger.info(f"Станция '{clean_name}' не найдена в кеше, запрашиваю OSM...")
    # V--- ИСПРАВЛЕНИЕ: Убрана лишняя часть ';out body;' ---V
    query = f'''
        [out:json];(
          node["railway"="station"]["name"~"^{clean_name}$",i];
          way["railway"="station"]["name"~"^{clean_name}$",i];
        );out center;
    '''
    try:
        response = await asyncio.to_thread(api.get, query)
        if not response or not response.features:
            logger.warning(f"Станция '{clean_name}' не найдена в OSM.")
            return None
        
        station_feature = response.features[0]
        geom = station_feature.get('geometry', {})
        coords = geom.get('center', {}).get('coordinates') or geom.get('coordinates')
        if not coords: return None
        lat, lon = coords[1], coords[0]
        
        await save_station_to_cache(clean_name, lat, lon)
        return {"lat": lat, "lon": lon}
    except Exception as e:
        logger.error(f"Ошибка при запросе координат станции '{clean_name}' в Overpass API: {e}")
        return None

async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    clean_from = _clean_station_name(from_station)
    clean_to = _clean_station_name(to_station)
    logger.info(f"Запрашиваю маршрут в OSM от '{clean_from}' до '{clean_to}'.")
    # V--- ИСПРАВЛЕНИЕ: Убрана лишняя часть ';out body;' ---V
    query = f'''
        [out:json][timeout:90];
        relation["type"="route"]["route"="train"]["from"~"^{clean_from}$",i]["to"~"^{clean_to}$",i];
        out geom;
    '''
    try:
        response = await asyncio.to_thread(api.get, query)
        if not response or not response.features:
            logger.warning(f"Маршрут от '{clean_from}' до '{clean_to}' не найден в OSM.")
            return None
        
        route = response.features[0]
        total_distance = 0.0
        for segment in route.geometry['coordinates']:
            for i in range(len(segment) - 1):
                p1 = (segment[i][1], segment[i][0])
                p2 = (segment[i+1][1], segment[i+1][0])
                total_distance += geodesic(p1, p2).kilometers
        return int(total_distance)
    except Exception as e:
        logger.error(f"Ошибка при расчете маршрута от '{clean_from}' до '{clean_to}': {e}")
        return None