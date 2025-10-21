# services/railway_router.py
from logger import get_logger
# ✅ Шаг 1: Импортируем КЛАСС OsmService, а не функцию
from services.osm_service import OsmService 
from utils.distance_calculator import haversine_distance
from config import RAILWAY_WINDING_FACTOR
from services.tariff_service import get_tariff_distance

logger = get_logger(__name__)

# ✅ Шаг 2: Создаем экземпляр сервиса OSM
osm_service = OsmService() 

async def get_remaining_distance_on_route(start_station: str, end_station: str, current_station: str) -> int | None:
    """
    Рассчитывает оставшееся расстояние до станции назначения.
    Приоритет: Тарифный справочник, затем OSM.
    """
    if not all([start_station, end_station, current_station]):
        return None
    
    if current_station == end_station:
        return 0

    logger.info(f"Начинаю расчет расстояния от '{current_station}' до '{end_station}'...")
    try:
        tariff_distance = await get_tariff_distance(current_station, end_station)
        if tariff_distance is not None:
            logger.info(f"✅ Расчет по ТАРИФУ: {tariff_distance} км.")
            return tariff_distance
    except Exception as e:
        logger.error(f"Ошибка при вызове тарифного сервиса, переключаюсь на OSM: {e}", exc_info=True)

    logger.warning(f"Не удалось рассчитать по тарифу. Переключаюсь на OSM.")
    try:
        # ✅ Шаг 3: Используем МЕТОД экземпляра класса
        current_coords = await osm_service.get_station_coordinates(current_station) 
        end_coords = await osm_service.get_station_coordinates(end_station)

        if current_coords and end_coords:
            distance_km = haversine_distance(
                lat1=current_coords.lat, lon1=current_coords.lon,
                lat2=end_coords.lat, lon2=end_coords.lon
            )
            final_distance = int(distance_km * RAILWAY_WINDING_FACTOR)
            logger.info(f"✅ Расчет по OSM: {distance_km:.2f} км * {RAILWAY_WINDING_FACTOR} = {final_distance} км.")
            return final_distance
        else:
            logger.warning(f"Не удалось получить координаты OSM для '{current_station}' или '{end_station}'.")
            return None
    except Exception as e:
        logger.error(f"Ошибка при расчете расстояния через OSM: {e}", exc_info=True)
        return None