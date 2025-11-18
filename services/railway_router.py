# services/railway_router.py
from logger import get_logger
from services.osm_service import OsmService 
from services.distance_calculator import haversine_distance
from config import RAILWAY_WINDING_FACTOR
# ✅ ИСПРАВЛЕНО: Корректный импорт асинхронной функции расчета тарифов
from services.tariff_service import get_tariff_distance 

logger = get_logger(__name__)

osm_service = OsmService() 

async def get_remaining_distance_on_route(start_station: str, end_station: str, current_station: str) -> int | None:
    """
    Рассчитывает оставшееся расстояние до станции назначения.
    Приоритет: Тарифный справочник (Прейскурант 10-01).
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
        # tariff_data - это теперь словарь, который содержит 'distance' и 'route_details'
        tariff_data = await get_tariff_distance(current_station, end_station)
        
        if tariff_data is not None and isinstance(tariff_data, dict):
            
            distance_value = tariff_data.get('distance')
            route = tariff_data.get('route_details') # Получаем детали маршрута
            
            if route:
                # ✅ ОБНОВЛЕННОЕ ЛОГИРОВАНИЕ С ТП
                logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {distance_value} км. ТП: {route['tpa_name']} -> {route['tpb_name']}")
            else:
                logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {distance_value} км. (ТП не требовались)")
            
            return distance_value
        
        elif tariff_data is None:
             # get_tariff_distance вернул None (маршрут не найден)
             logger.info(f"Тарифный сервис не нашел маршрут для {current_station} -> {end_station}.")
             pass
        else:
             # На всякий случай, если вернулось что-то странное
             logger.error(f"Тарифный сервис вернул неожиданный тип данных: {type(tariff_data)}")
             pass
            
    except Exception as e:
        logger.error(f"⚠️ Ошибка при вызове тарифного сервиса: {e}", exc_info=True)

    # --- Запасной вариант ---
    logger.info(f"Запасной расчет по OSM для '{current_station}' -> '{end_station}' отключен. Используется только тарифный сервис.")
    return None