# services/railway_router.py
from logger import get_logger
# ❗️--- ИСПРАВЬТЕ ИМПОРТ ЗДЕСЬ, если имя класса другое ---❗️
from services.osm_service import OsmService 
from services.distance_calculator import haversine_distance
from config import RAILWAY_WINDING_FACTOR
from services.tariff_service import get_tariff_distance

logger = get_logger(__name__)

# ❗️--- ИСПРАВЬТЕ СОЗДАНИЕ ЭКЗЕМПЛЯРА ЗДЕСЬ, если имя класса другое ---❗️
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
    
    # --- Попытка расчета по тарифному справочнику (Аналог логики /distance) ---
    try:
        # 1. tariff_data будет СЛОВАРЕМ (dict) или None
        tariff_data = await get_tariff_distance(current_station, end_station)
        
        # --- ⭐️ НАЧАЛО ИСПРАВЛЕНИЯ ⭐️ ---
        # 2. Проверяем, что вернулся СЛОВАРЬ
        if tariff_data is not None and isinstance(tariff_data, dict):
            
            # 3. Извлекаем числовое значение 'distance'
            distance_value = tariff_data.get('distance')
            
            # 4. Логгируем только число
            logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {distance_value} км.")
            
            # 5. Возвращаем только число (int | None)
            return distance_value
        
        elif tariff_data is None:
             # get_tariff_distance вернул None (маршрут не найден)
             logger.info(f"Тарифный сервис не нашел маршрут для {current_station} -> {end_station}.")
             pass
        else:
             # На всякий случай, если вернулось что-то странное
             logger.error(f"Тарифный сервис вернул неожиданный тип данных: {type(tariff_data)}")
             pass
        # --- ⭐️ КОНЕЦ ИСПРАВЛЕНИЯ ⭐️ ---
            
    except Exception as e:
        # Этот блок 'except' теперь корректно привязан к 'try'
        logger.error(f"⚠️ Ошибка при вызове тарифного сервиса: {e}", exc_info=True)

    # --- Запасной вариант: Отключен после внедрения тарифа ---
    logger.info(f"Запасной расчет по OSM для '{current_station}' -> '{end_station}' отключен. Используется только тарифный сервис.")
    return None