# services/osm_service.py
import asyncio
import re
import httpx
from geopy.distance import geodesic
from logger import get_logger
from db import SessionLocal
from models import RailwayStation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)
logger.info("<<<<< ЗАГРУЖЕНА НОВАЯ ВЕРСИЯ OSM SERVICE v11.0 (финальная) >>>>>")

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

def get_canonical_name(station_name: str) -> str:
    """
    Приводит любое название станции к единому, 'каноническому' виду для использования в качестве ключа кеша.
    УДАЛЯЕТ любой текст в скобках и приводит цифры к единому формату.
    """
    # 1. Удаляем любой текст в скобках, например, (ЭКСП.) или (982300)
    name = re.sub(r'\s*\([^)]*\)', '', station_name).strip()
    
    # 2. Список суффиксов и слов-уточнений для удаления
    suffixes_to_remove = [
        "ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ",
        "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ", "ПАРК"
    ]
    for suffix in suffixes_to_remove:
        name = re.sub(r'[\s-]+' + re.escape(suffix) + r'\b', '', name, flags=re.IGNORECASE)

    # 3. Унифицируем римские цифры в арабские
    name = re.sub(r'\s+I$', ' 1', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+II$', ' 2', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+III$', ' 3', name, flags=re.IGNORECASE)
    
    # 4. Унифицируем разделитель перед цифрой: любой пробел или дефис -> один дефис
    name = re.sub(r'[\s-]+\s*([1-9])$', r'-\1', name)
    
    return name.strip().upper()

async def _make_overpass_request(query: str) -> dict | None:
    """Отправляет запрос к Overpass API и возвращает JSON ответ."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(OVERPASS_API_URL, data={'data': query})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP при запросе к Overpass API: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса к Overpass API: {e}", exc_info=True)
            return None

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
        logger.info(f"Станция '{original_station_name}' найдена в кеше по каноническому имени '{canonical_name}'.")
        return {"lat": cached_station.latitude, "lon": cached_station.longitude}

    logger.info(f"Станция '{original_station_name}' не найдена в кеше, запрашиваю OSM по варианту '{station_name_for_search}'...")
    query = f'''
        [out:json];
        (
          node["railway"~"station|yard"]["name"~"{station_name_for_search}",i];
          way["railway"~"station|yard"]["name"~"{station_name_for_search}",i];
        );
        out center;
    '''
    data = await _make_overpass_request(query)
    if not data or not data.get('elements'):
        return None
    
    elements = data['elements']
    best_element = elements[0]
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

    await save_station_to_cache(canonical_name, lat, lon)
    logger.info(f"Найдено! Станция '{original_station_name}' сохранена в кеш как '{canonical_name}'.")
    return {"lat": lat, "lon": lon}


async def fetch_route_distance(from_station: str, to_station: str) -> int | None:
    """Эта функция не используется в текущей логике, оставлена для совместимости."""
    return None