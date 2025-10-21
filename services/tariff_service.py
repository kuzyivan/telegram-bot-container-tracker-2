# services/tariff_service.py
import re
import asyncio
import os # <-- Добавляем os
import sys # <-- Добавляем sys
from logger import get_logger

logger = get_logger(__name__) 

# --- Добавляем корень проекта в sys.path ---
# Определяем путь к текущему файлу (tariff_service.py)
current_file_path = os.path.abspath(__file__)
# Находим папку services/
services_dir = os.path.dirname(current_file_path)
# Находим корень проекта (папку выше services/)
project_root_dir = os.path.dirname(services_dir)
# Добавляем корень проекта в sys.path, если его там нет
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)
    logger.debug(f"[Tariff] Добавлен {project_root_dir} в sys.path") # Для отладки
# ---------------------------------------------

# --- Шаг 1: Импорт вашего калькулятора ---
try:
    # Теперь Python должен найти zdtarif_bot, т.к. корень проекта в sys.path
    from zdtarif_bot.rail_calculator import get_distance_sync
    logger.info("✅ [Tariff] Сервис 'zdtarif_bot' (get_distance_sync) успешно импортирован.")
except ImportError as e:
    logger.error(f"❌ [Tariff] НЕ УДАЛОСЬ импортировать 'zdtarif_bot.rail_calculator': {e}", exc_info=True) # Добавим traceback
    get_distance_sync = None
except Exception as e: # Ловим другие возможные ошибки при импорте
     logger.error(f"❌ [Tariff] НЕПРЕДВИДЕННАЯ ОШИБКА при импорте 'zdtarif_bot.rail_calculator': {e}", exc_info=True)
     get_distance_sync = None


def _extract_station_code(station_name: str | None) -> str | None:
    """Извлекает код станции."""
    if not station_name: return None
    match = re.search(r'\((\d+)\)', station_name)
    if match: return match.group(1)
    logger.warning(f"Не удалось извлечь код из станции: '{station_name}'")
    return None

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> int | None:
    """Рассчитывает тарифное расстояние."""
    if not get_distance_sync:
        logger.error("[Tariff] Сервис zdtarif_bot не импортирован или не инициализирован. Расчет невозможен.")
        return None

    from_station_code = _extract_station_code(from_station_name)
    to_station_code = _extract_station_code(to_station_name)

    if not from_station_code or not to_station_code:
        logger.info(f"[Tariff] Недостаточно кодов станций для расчета: {from_station_name} -> {to_station_name}")
        return None

    try:
        logger.info(f"[Tariff] Запуск расчета в потоке: {from_station_code} -> {to_station_code}")
        distance = await asyncio.to_thread(
            get_distance_sync,
            from_station_code,
            to_station_code
        )

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