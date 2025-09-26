# services/osm_service.py
import asyncio
import re
import httpx
from logger import get_logger
from db import SessionLocal
from models import RailwayStation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)
logger.info("<<<<< ЗАГРУЖЕНА НОВАЯ ВЕРСИЯ OSM SERVICE v15.0 (финальная, исправленная) >>>>>")

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

def get_canonical_name(station_name: str) -> str:
    name = re.sub(r'\s*\([^)]*\)', '', station_name).strip()
    suffixes_to_remove = [
        "ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ",
        "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ", "ПАРК"
    ]
    for suffix in suffixes_to_remove:
        name = re.sub(r'[\s-]+' + re.escape(suffix) + r'\b', '', name, flags=re.IGNORECASE)

    name = re.sub(r'\s+I$', ' 1', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+II$', ' 2', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+III$', ' 3', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s-]+\s*([1-9])$', r'-\1', name)
    
    return name.strip().upper()

# --- ИСПРАВЛЕНИЕ: ВОЗВРАЩАЕМ ФУНКЦИЮ НА МЕСТО ---
def generate_name_variations(station_name: str) -> list[str]:
    """
    Генерирует список возможных вариантов написания названия станции для поиска в OSM.
    """
    name = re.sub(r'\s*\([^)]*\)', '', station_name).strip()
    suffixes_to_remove = ["ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ", "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ", "ЭКСП", "ПАРК"]
    base_name = name
    for suffix in suffixes_to_remove:
        base_name = re.sub(r'[\s-]+' + re.escape(suffix) + r'\b', '', base_name, flags=re.IGNORECASE)
    base_name = base_name.strip()
    variations = {base_name}
    match = re.search(r'(.+?)[\s-]*((?:[IVX]+)|(?:[0-9]+))$', base_name)
    if match:
        name_part, num_part = match.group(1).strip(), match.group(2)
        arabic, roman = "", ""
        if num_part.isdigit():
            arabic = num_part
            roman_map = {'1': 'I', '2': 'II', '3': 'III', '4': 'IV'}
            roman = roman_map.get(arabic, "")
        else:
            roman = num_part
            roman_map_rev = {'I': '1', 'II': '2', 'III': '3', 'IV': '4'}
            arabic = roman_map_rev.get(roman, "")
        variations.add(name_part)
        if arabic:
            variations.add(f"{name_part}-{arabic}")
            variations.add(f"{name_part} {arabic}")
        if roman:
            variations.add(f"{name_part}-{roman}")
            variations.add(f"{name_part} {roman}")
    return sorted(list(variations), key=len, reverse=True)

async def _make_overpass_request(query: str) -> dict | None:
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(OVERPASS_API_URL, data={'data': query})
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

async def get_station_from_cache(canonical_name: str) -> RailwayStation | None:
    async with SessionLocal() as session:
        result = await session.execute(select(RailwayStation).where(RailwayStation.name == canonical_name))
        return result.scalar_one_or_none()

async def save_station_to_cache(canonical_name: str, lat: float, lon: float):
    async with SessionLocal() as session:
        stmt = pg_insert(RailwayStation).values(name=canonical_name, latitude=lat, longitude=lon).on_conflict_do_nothing(index_elements=['name'])
        await session.execute(stmt)
        await session.commit()

async def fetch_station_coords(station_name_for_search: str, original_station_name: str) -> dict | None:
    canonical_name = get_canonical_name(original_station_name)
    cached_station = await get_station_from_cache(canonical_name)
    if cached_station:
        logger.info(f"Станция '{original_station_name}' найдена в кеше по имени '{canonical_name}'.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    logger.info(f"Станция '{original_station_name}' не найдена в кеше, запрашиваю OSM по варианту '{station_name_for_search}'...")
    
    search_criteria = "station|yard|halt|stop|stop_position"
    query = f'''
        [out:json];
        (
          node["railway"~"{search_criteria}"]["name"~"{station_name_for_search}",i];
          way["railway"~"{search_criteria}"]["name"~"{station_name_for_search}",i];
        );
        out center;
    '''
    
    data = await _make_overpass_request(query)
    if not data or not data.get('elements'):
        return None
    
    elements = data['elements']
    best_element = elements[0]
    for el_type in ['station', 'yard', 'halt', 'stop_position', 'stop']:
        for el in elements:
            if el.get('tags', {}).get('railway') == el_type:
                best_element = el
                break
        else:
            continue
        break
    
    lat, lon = 0.0, 0.0
    if 'center' in best_element:
        lat, lon = best_element['center']['lat'], best_element['center']['lon']
    elif 'lat' in best_element:
        lat, lon = best_element['lat'], best_element['lon']
    else:
        return None

    await save_station_to_cache(canonical_name, lat, lon)
    logger.info(f"Найдено! Станция '{original_station_name}' сохранена в кеш как '{canonical_name}'.")
    return {"lat": lat, "lon": lon}

async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    return None