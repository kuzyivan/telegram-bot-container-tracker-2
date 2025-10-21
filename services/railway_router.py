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
    # ПРИМЕЧАНИЕ: Очистка кода в скобках (940608) происходит в ядре zdtarif_bot.
    # Мы передаем полные имена.
    start_station = start_station.strip()
    end_station = end_station.strip()
    current_station = current_station.strip()

    if current_station == end_station:
        logger.info(f"Текущая станция '{current_station}' совпадает со станцией назначения. Расстояние: 0 км.")
        return 0

    logger.info(f"Начинаю расчет расстояния от '{current_station}' до '{end_station}'...")
    
    # --- Попытка расчета по тарифному справочнику (Аналог логики /distance) ---
    try:
        # ✅ ПЕРЕДАЕМ CURRENT_STATION и END_STATION (полностью, как они есть)
        tariff_distance = await get_tariff_distance(current_station, end_station)
        
        if tariff_distance is not None:
            logger.info(f"✅ Расчет выполнен по ТАРИФНОМУ СПРАВОЧНИКУ. Расстояние: {tariff_distance} км.")
            return tariff_distance
        else:
             pass
    except Exception as e:
        logger.error(f"⚠️ Ошибка при вызове тарифного сервиса: {e}", exc_info=True)

    # --- Запасной вариант: Отключен после внедрения тарифа ---
    logger.info(f"Запасной расчет по OSM для '{current_station}' -> '{end_station}' отключен. Используется только тарифный сервис.")
    return None