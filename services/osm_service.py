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
logger.info("<<<<< ЗАГРУЖЕНА НОВАЯ ВЕРСИЯ OSM SERVICE v7.0 (с каноническим кешированием) >>>>>")

api = overpass.API(timeout=90)

def get_canonical_name(station_name: str) -> str:
    """Возвращает базовое, 'каноническое' имя станции для использования в качестве ключа кеша."""
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip() # Убираем код
    # Можно добавить и другие правила, но для кеша достаточно этого
    return name.upper()

async def get_station_from_cache(canonical_name: str) -> RailwayStation | None:
    """Ищет станцию в нашей локальной БД (кеше) по каноническому имени."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(RailwayStation).where(RailwayStation.name == canonical_name)
        )
        return result.scalar_one_or_none()

async def save_station_to_cache(canonical_name: str, lat: float, lon: float):
    """Сохраняет найденную станцию в нашу локальную БД под каноническим именем."""
    async with SessionLocal() as session:
        stmt = pg_insert(RailwayStation).values(
            name=canonical_name, latitude=lat, longitude=lon
        ).on_conflict_do_nothing(index_elements=['name'])
        await session.execute(stmt)
        await session.commit()

async def fetch_station_coords(station_name_for_search: str, original_station_name: str) -> dict | None:
    """
    Ищет координаты станции. Сначала проверяет кеш по каноническому имени,
    затем ищет в OSM по имени для поиска.
    """
    canonical_name = get_canonical_name(original_station_name)
    
    cached_station = await get_station_from_cache(canonical_name)
    if cached_station:
        logger.info(f"Станция '{original_station_name}' найдена в кеше по имени '{canonical_name}'.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    logger.info(f"Станция '{original_station_name}' не найдена в кеше, запрашиваю OSM по варианту '{station_name_for_search}'...")
    query = f'''
        [out:json];(
          node["railway"~"station|yard"]["name"~"^{station_name_for_search}$",i];
          way["railway"~"station|yard"]["name"~"^{station_name_for_search}$",i];
        );out center;
    '''
    try:
        response = await asyncio.to_thread(api.get, query)
        if not response or not response.features:
            # logger.warning(f"Вариант '{station_name_for_search}' не найден в OSM.") # Логируем это в кешере
            return None
        
        station_feature = response.features[0]
        geom = station_feature.get('geometry', {})
        coords = geom.get('center', {}).get('coordinates') or geom.get('coordinates')
        if not coords: return None
        lat, lon = coords[1], coords[0]
        
        await save_station_to_cache(canonical_name, lat, lon)
        logger.info(f"Найдено! Станция '{original_station_name}' сохранена в кеш как '{canonical_name}'.")
        return {"lat": lat, "lon": lon}
    except Exception as e:
        logger.error(f"Ошибка при запросе координат для '{station_name_for_search}' в Overpass API: {e}")
        return None

# Функция fetch_route_distance остается без изменений, так как она не использует кеш
async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    # ... (код без изменений) ...
    # ...
    pass # Заглушка, чтобы показать, что код здесь не меняется