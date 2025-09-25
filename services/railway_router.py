# services/railway_router.py
from typing import Optional
import re
from services.osm_service import fetch_station_coords
from services.distance_calculator import haversine_distance, RAILWAY_WINDING_FACTOR
from logger import get_logger

logger = get_logger(__name__)

def _clean_station_name(station_name: str) -> str:
    """Очищает имя станции от кодов и уточнений для поиска координат."""
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip()
    name = name.replace('ЭКСП.', '').strip()
    return name

async def get_remaining_distance_on_route(
    start_station: str,
    end_station: str,
    current_station: str
) -> Optional[int]:
    """
    Простой и надежный расчет расстояния:
    1. Получает координаты текущей и конечной станций из OSM.
    2. Считает расстояние между ними по прямой.
    3. Применяет коэффициент извилистости ж/д путей.
    """
    
    clean_current = _clean_station_name(current_station)
    clean_end = _clean_station_name(end_station)

    logger.info(f"Начинаю прямой расчет расстояния от '{clean_current}' до '{clean_end}'.")
    
    # Получаем координаты для обеих станций
    current_coords = await fetch_station_coords(current_station) # Передаем оригинал, т.к. osm_service сам чистит
    end_coords = await fetch_station_coords(end_station)
    
    if not current_coords or not end_coords:
        logger.error(f"Не удалось получить координаты для одной из станций: '{clean_current}' или '{clean_end}'.")
        return None

    # Рассчитываем расстояние
    direct_distance = haversine_distance(
        current_coords['lat'], current_coords['lon'],
        end_coords['lat'], end_coords['lon']
    )
    
    estimated_distance = int(direct_distance * RAILWAY_WINDING_FACTOR)
    logger.info(f"Расчетное расстояние по прямой с коэффициентом: {estimated_distance} км.")
    
    return estimated_distance