# services/railway_router.py
from logger import get_logger
# ❗️--- ИСПРАВЬТЕ ИМПОРТ ЗДЕСЬ, если имя класса другое ---❗️
from services.osm_service import OsmService 
from utils.distance_calculator import haversine_distance
from config import RAILWAY_WINDING_FACTOR
from services.tariff_service import get_tariff_distance

logger = get_logger(__name__)

# ❗️--- ИСПРАВЬТЕ СОЗДАНИЕ ЭКЗЕМПЛЯРА ЗДЕСЬ, если имя класса другое ---❗️
osm_service = OsmService() 

async def get_remaining_distance_on_route(start_station: str, end_station: str, current_station: str) -> int | None:
    """
    Рассчитывает оставшееся расстояние до станции назначения.
    Приоритет: Тарифный справочник, затем OSM.
    """
    if not all([start_station, end_station, current_station]):
        logger.warning("Недостаточно данных для расчета расстояния (start, end или current пустые).")
        return None
    
    # Нормализуем названия станций на всякий случай (убираем лишние пробелы)
    start_station = start_station.strip()
    end_station = end_station.strip()
    current_station = current_station.strip()

    if current_station == end_station:
        logger.info(f"Текущая станция '{current_station}' совпадает со станцией назначения. Расстояние: 0 км.")
        return 0

    logger.info(f"Начинаю расчет расстояния от '{current_station}' до '{end_station}'...")
    
    # --- Попытка расчета по тарифному справочнику ---
    try:
        tariff_distance = await get_tariff_distance(current_station, end_station)
        if tariff_distance is not None:
            logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {tariff_distance} км.")
            return tariff_distance
        else:
            # Лог о том, что тариф не найден, уже есть внутри get_tariff_distance
             pass
    except Exception as e:
        logger.error(f"⚠️ Ошибка при вызове тарифного сервиса, переключаюсь на OSM: {e}", exc_info=True)

    # --- Запасной вариант: Расчет по OSM ---
    logger.warning(f"Не удалось рассчитать по тарифу для '{current_station}' -> '{end_station}'. Переключаюсь на OSM.")
    try:
        current_coords = await osm_service.get_station_coordinates(current_station) 
        end_coords = await osm_service.get_station_coordinates(end_station)

        if current_coords and end_coords:
            distance_km = haversine_distance(
                lat1=current_coords.lat, lon1=current_coords.lon,
                lat2=end_coords.lat, lon2=end_coords.lon
            )
            # Применяем коэффициент извилистости
            final_distance = int(distance_km * RAILWAY_WINDING_FACTOR)
            # Добавим проверку, чтобы не возвращать 0, если станции разные, но очень близко
            if final_distance == 0 and distance_km > 0.1: # Если реальное расстояние больше 100м
                 final_distance = 1 # Возвращаем хотя бы 1 км
                 
            logger.info(f"✅ Расчет по OSM: {distance_km:.2f} км * {RAILWAY_WINDING_FACTOR} = {final_distance} км.")
            return final_distance
        else:
            logger.warning(f"Не удалось получить координаты OSM для '{current_station}' ({current_coords}) или '{end_station}' ({end_coords}).")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка при расчете расстояния через OSM: {e}", exc_info=True)
        return None