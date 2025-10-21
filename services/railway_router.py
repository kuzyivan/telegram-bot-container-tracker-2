# services/railway_router.py
from logger import get_logger
from services.osm_service import get_station_coordinates
from utils.distance_calculator import haversine_distance
from config import RAILWAY_WINDING_FACTOR

# ✅ Шаг 1: Импортируем новый сервис
from services.tariff_service import get_tariff_distance

logger = get_logger(__name__)

async def get_remaining_distance_on_route(start_station: str, end_station: str, current_station: str) -> int | None:
    """
    Рассчитывает оставшееся расстояние до станции назначения.
    
    Приоритет 1: Тарифный справочник (точно).
    Приоритет 2: Расчет по координатам OSM (приблизительно).
    """
    if not all([start_station, end_station, current_station]):
        return None
    
    # Если текущая станция и есть станция назначения - расстояние 0
    if current_station == end_station:
        return 0

    # ✅ Шаг 2: Сначала пытаемся рассчитать по тарифному справочнику
    logger.info(f"Начинаю расчет расстояния от '{current_station}' до '{end_station}'...")
    try:
        tariff_distance = await get_tariff_distance(current_station, end_station)
        if tariff_distance is not None:
            logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {tariff_distance} км.")
            return tariff_distance
    except Exception as e:
        logger.error(f"Ошибка при вызове тарифного сервиса, переключаюсь на OSM: {e}", exc_info=True)

    # ✅ Шаг 3: Если тарифный сервис не помог, используем OSM как запасной вариант
    logger.warning(f"Не удалось рассчитать по тарифу. Переключаюсь на запасной метод (OSM).")
    try:
        current_coords = await get_station_coordinates(current_station)
        end_coords = await get_station_coordinates(end_station)

        if current_coords and end_coords:
            distance_km = haversine_distance(
                lat1=current_coords.lat, lon1=current_coords.lon,
                lat2=end_coords.lat, lon2=end_coords.lon
            )
            final_distance = int(distance_km * RAILWAY_WINDING_FACTOR)
            logger.info(f"✅ Расчет по OSM: {distance_km:.2f} км * {RAILWAY_WINDING_FACTOR} = {final_distance} км.")
            return final_distance
        else:
            logger.warning(f"Не удалось получить координаты для одной из станций: '{current_station}' или '{end_station}'.")
            return None
    except Exception as e:
        logger.error(f"Ошибка при расчете расстояния через OSM: {e}", exc_info=True)
        return None