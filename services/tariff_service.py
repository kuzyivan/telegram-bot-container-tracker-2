# services/tariff_service.py
import re
import asyncio
from logger import get_logger

# --- Шаг 1: Импорт вашего калькулятора ---
try:
    # Python будет искать этот файл по пути: ./zdtarif_bot/rail_calculator.py
    from zdtarif_bot.rail_calculator import get_distance_sync
    
    logger.info("✅ [Tariff] Сервис 'zdtarif_bot' (get_distance_sync) успешно импортирован.")
    # Примечание: При этом импорте zdtarif_bot автоматически загрузит все CSV-файлы в память.
except ImportError as e:
    logger.error(f"❌ [Tariff] НЕ УДАЛОСЬ импортировать 'zdtarif_bot.rail_calculator': {e}")
    get_distance_sync = None

logger = get_logger(__name__)

def _extract_station_code(station_name: str | None) -> str | None:
    """
    Надежно извлекает код станции из строки формата 'НАЗВАНИЕ (КОД)'.
    """
    if not station_name:
        return None
    match = re.search(r'\((\d+)\)', station_name)
    if match:
        return match.group(1)
    logger.warning(f"Не удалось извлечь код из станции: '{station_name}'")
    return None

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> int | None:
    """
    Рассчитывает тарифное расстояние, вызывая синхронный сервис zdtarif_bot
    в отдельном потоке, чтобы не блокировать основного бота.
    """
    if not get_distance_sync:
        logger.error("[Tariff] Сервис zdtarif_bot не импортирован. Расчет невозможен.")
        return None

    from_station_code = _extract_station_code(from_station_name)
    to_station_code = _extract_station_code(to_station_name)

    if not from_station_code or not to_station_code:
        logger.info(f"[Tariff] Недостаточно кодов станций для расчета: {from_station_name} -> {to_station_name}")
        return None

    try:
        # --------------------------------------------------------------------
        # ✅ РЕАЛИЗАЦИЯ (вместо заглушки)
        # --------------------------------------------------------------------
        logger.info(f"[Tariff] Запуск расчета в потоке: {from_station_code} -> {to_station_code}")
        
        # Вызываем вашу синхронную функцию в отдельном потоке,
        # чтобы она не "заморозила" асинхронного бота.
        distance = await asyncio.to_thread(
            get_distance_sync,  # Ваша функция
            from_station_code,      # Первый аргумент
            to_station_code       # Второй аргумент
        )
        
        # --------------------------------------------------------------------

        if distance is not None and int(distance) > 0:
            distance_int = int(distance)
            logger.info(f"✅ [Tariff] Расстояние получено: {from_station_code} -> {to_station_code} = {distance_int} км.")
            return distance_int
        else:
            logger.info(f"[Tariff] Расстояние не найдено (сервис вернул 0 или None).")
            return None
            
    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при вызове zdtarif_bot: {e}", exc_info=True)
        return None