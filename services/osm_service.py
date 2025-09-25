# services/osm_service.py
import overpass
import asyncio
from geopy.distance import geodesic
from logger import get_logger
from db import SessionLocal
from models import RailwayStation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)

# Инициализируем API-клиент. Таймаут увеличен для сложных запросов.
api = overpass.API(timeout=90)

# --- Кеширование ---
async def get_station_from_cache(name: str) -> RailwayStation | None:
    """Ищет станцию в нашей локальной БД (кеше)."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(RailwayStation).where(RailwayStation.name == name.upper())
        )
        return result.scalar_one_or_none()

async def save_station_to_cache(name: str, lat: float, lon: float):
    """Сохраняет найденную станцию в нашу локальную БД."""
    async with SessionLocal() as session:
        stmt = pg_insert(RailwayStation).values(
            name=name.upper(),
            latitude=lat,
            longitude=lon
        ).on_conflict_do_nothing(index_elements=['name'])
        await session.execute(stmt)
        await session.commit()

# --- Функции для работы с API ---
async def fetch_station_coords(station_name: str) -> dict | None:
    """
    Ищет ж/д станцию в OpenStreetMap по названию и возвращает её координаты.
    Сначала проверяет локальный кеш (БД).
    """
    # 1. Проверка кеша
    cached_station = await get_station_from_cache(station_name)
    if cached_station:
        logger.info(f"Станция '{station_name}' найдена в кеше.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    # 2. Если в кеше нет, идем в OSM
    logger.info(f"Станция '{station_name}' не найдена в кеше, запрашиваю OSM...")
    query = f'''
        [out:json];
        (
          node["railway"="station"]["name"~"^{station_name}$",i];
          way["railway"="station"]["name"~"^{station_name}$",i];
        );
        out center;
    '''
    try:
        response = await asyncio.to_thread(api.get, query)
        if not response or not response.features:
            logger.warning(f"Станция '{station_name}' не найдена в OSM.")
            return None
        
        station_feature = response.features[0]
        geom = station_feature.get('geometry', {})
        
        # Координаты могут быть в разных местах в зависимости от типа объекта
        if 'center' in geom:
            coords = geom['center']['coordinates']
        else:
            coords = geom.get('coordinates', [])

        if not coords:
            return None

        lat, lon = coords[1], coords[0]
        
        # 3. Сохраняем в кеш на будущее
        await save_station_to_cache(station_name, lat, lon)
        
        return {"lat": lat, "lon": lon}
        
    except Exception as e:
        logger.error(f"Ошибка при запросе координат станции '{station_name}' в Overpass API: {e}")
        return None

async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    """
    Находит ж/д маршрут между станциями в OSM и считает его длину в км.
    """
    logger.info(f"Запрашиваю маршрут в OSM от '{from_station}' до '{to_station}'.")
    query = f'''
        [out:json][timeout:90];
        relation
          ["type"="route"]["route"="train"]
          ["from"~"^{from_station}$",i]
          ["to"~"^{to_station}$",i];
        out geom;
    '''
    try:
        response = await asyncio.to_thread(api.get, query)
        if not response or not response.features:
            logger.warning(f"Маршрут от '{from_station}' до '{to_station}' не найден в OSM.")
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
        logger.error(f"Ошибка при расчете маршрута от '{from_station}' до '{to_station}': {e}")
        return None