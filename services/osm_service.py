# services/osm_service.py
import asyncio
import re
import httpx  # <--- Используем httpx вместо overpass
from geopy.distance import geodesic
from logger import get_logger
from db import SessionLocal
from models import RailwayStation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)
logger.info("<<<<< ЗАГРУЖЕНА НОВАЯ ВЕРСИЯ OSM SERVICE v6.0 (на базе httpx) >>>>>")

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

def _clean_station_name(station_name: str) -> str:
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip()
    name = re.sub(r'[\s-]+(СОРТИРОВОЧНЫЙ|ГЛАВНЫЙ|ВОСТОЧНЫЙ|ЗАПАДНЫЙ|СЕВЕРНЫЙ|ЮЖНЫЙ)$', '', name, flags=re.IGNORECASE)
    return name.strip()

async def _make_overpass_request(query: str) -> dict | None:
    """Отправляет запрос к Overpass API и возвращает JSON ответ."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(OVERPASS_API_URL, data={'data': query})
            response.raise_for_status()  # Вызовет исключение для статусов 4xx/5xx
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP при запросе к Overpass API: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса к Overpass API: {e}", exc_info=True)
            return None

async def get_station_from_cache(name: str) -> RailwayStation | None:
    # ... (код без изменений)
    async with SessionLocal() as session:
        result = await session.execute(select(RailwayStation).where(RailwayStation.name == name.upper()))
        return result.scalar_one_or_none()

async def save_station_to_cache(name: str, lat: float, lon: float):
    # ... (код без изменений)
    async with SessionLocal() as session:
        stmt = pg_insert(RailwayStation).values(name=name.upper(), latitude=lat, longitude=lon).on_conflict_do_nothing(index_elements=['name'])
        await session.execute(stmt)
        await session.commit()

async def fetch_station_coords(station_name: str) -> dict | None:
    clean_name = _clean_station_name(station_name)
    # Используем оригинальное имя для кеша, чтобы избежать коллизий
    original_clean_name = station_name.split('(')[0].strip()
    
    cached_station = await get_station_from_cache(original_clean_name)
    if cached_station:
        logger.info(f"Станция '{original_clean_name}' найдена в кеше.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    logger.info(f"Станция '{clean_name}' не найдена в кеше, запрашиваю OSM...")
    query = f'''
        [out:json];
        (
          node["railway"~"station|yard"]["name"~"{clean_name}",i];
          way["railway"~"station|yard"]["name"~"{clean_name}",i];
        );
        out center;
    '''
    data = await _make_overpass_request(query)
    if not data or not data.get('elements'):
        logger.warning(f"Станция '{clean_name}' не найдена в OSM.")
        return None

    elements = data['elements']
    best_element = elements[0]
    # Простой эвристический выбор лучшего результата
    for el in elements:
        if el.get('tags', {}).get('railway') == 'station':
            best_element = el
            break
    
    lat, lon = 0.0, 0.0
    if 'center' in best_element:
        lat, lon = best_element['center']['lat'], best_element['center']['lon']
    elif 'lat' in best_element:
        lat, lon = best_element['lat'], best_element['lon']
    else:
        return None

    await save_station_to_cache(original_clean_name, lat, lon)
    return {"lat": lat, "lon": lon}


async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    # Эта функция имеет мало шансов на успех, но мы оставляем её для полноты
    clean_from = _clean_station_name(from_station)
    clean_to = _clean_station_name(to_station)
    logger.info(f"Запрашиваю маршрут в OSM от '{clean_from}' до '{clean_to}'.")
    query = f'''
        [out:json][timeout:90];
        relation["type"="route"]["route"="train"]["from"~"^{clean_from}$",i]["to"~"^{clean_to}$",i];
        out geom;
    '''
    # ... (эта часть пока остается без изменений, т.к. она менее критична)
    # Если и она будет сбоить, её тоже можно будет переписать на httpx
    return None