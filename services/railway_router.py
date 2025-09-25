# services/railway_router.py
from typing import Optional
from services.osm_service import fetch_route_distance, fetch_station_coords
from services.distance_calculator import haversine_distance, RAILWAY_WINDING_FACTOR
from logger import get_logger

logger = get_logger(__name__)

async def get_remaining_distance_on_route(
    start_station: str,
    end_station: str,
    current_station: str
) -> Optional[int]:
    """
    Вычисляет оставшееся расстояние до конечной станции.
    Сначала пытается найти полный маршрут в OSM. Если не удается,
    считает расстояние по прямой с коэффициентом.
    """
    # Способ 1: Попытка найти точный маршрут в OSM (самый точный)
    distance = await fetch_route_distance(current_station, end_station)
    if distance is not None:
        logger.info(f"Найдено точное расстояние по маршруту OSM: {distance} км.")
        return distance

    # Способ 2: Если маршрут не найден, считаем по прямой (менее точный)
    logger.warning(f"Точный маршрут не найден, вычисляю расстояние по прямой для '{current_station}' -> '{end_station}'.")
    current_coords = await fetch_station_coords(current_station)
    end_coords = await fetch_station_coords(end_station)

    if current_coords and end_coords:
        direct_distance = haversine_distance(
            current_coords['lat'], current_coords['lon'],
            end_coords['lat'], end_coords['lon']
        )
        estimated_distance = int(direct_distance * RAILWAY_WINDING_FACTOR)
        logger.info(f"Расчетное расстояние по прямой с коэффициентом: {estimated_distance} км.")
        return estimated_distance
    
    logger.error(f"Не удалось получить координаты для одной из станций: '{current_station}' или '{end_station}'.")
    return None