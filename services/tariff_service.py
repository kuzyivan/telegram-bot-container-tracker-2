# services/tariff_service.py
import re
import asyncio
import os
import sys
from logger import get_logger

logger = get_logger(__name__) 

# --- Добавляем корень проекта в sys.path ---
# Определяем путь к текущему файлу (tariff_service.py)
current_file_path = os.path.abspath(__file__)
services_dir = os.path.dirname(current_file_path)
project_root_dir = os.path.dirname(services_dir)
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)
    logger.debug(f"[Tariff] Добавлен {project_root_dir} в sys.path") 

# --- Шаг 1: Импорт вашего калькулятора ---
try:
    from zdtarif_bot.rail_calculator import get_distance_sync
    logger.info("✅ [Tariff] Сервис 'zdtarif_bot' (get_distance_sync) успешно импортирован.")
except ImportError as e:
    logger.error(f"❌ [Tariff] НЕ УДАЛОСЬ импортировать 'zdtarif_bot.rail_calculator': {e}", exc_info=True) 
    get_distance_sync = None
except Exception as e: 
     logger.error(f"❌ [Tariff] НЕПРЕДВИДЕННАЯ ОШИБКА при импорте 'zdtarif_bot.rail_calculator': {e}", exc_info=True)
     get_distance_sync = None


# --- УДАЛЯЕМ НЕНУЖНУЮ ФУНКЦИЮ _extract_station_code ---


async def get_tariff_distance(from_station_name: str, to_station_name: str) -> int | None:
    """
    Рассчитывает тарифное расстояние, передавая полные названия станций в ядро.
    Ядро zdtarif_bot само находит код станции.
    """
    if not get_distance_sync:
        logger.error("[Tariff] Сервис zdtarif_bot не импортирован или не инициализирован. Расчет невозможен.")
        return None

    if not from_station_name or not to_station_name:
        logger.info(f"[Tariff] Недостаточно данных для расчета: {from_station_name} -> {to_station_name}")
        return None

    try:
        # ✅ ИЗМЕНЕНИЕ: Мы передаем полные/необработанные названия станций в ядро.
        # Ядро должно само найти код и рассчитать расстояние.
        logger.info(f"[Tariff] Запуск расчета в потоке: {from_station_name} -> {to_station_name}")
        
        distance_result = await asyncio.to_thread(
            get_distance_sync,
            from_station_name, # Передаем полное имя, например, 'чемской'
            to_station_name    # Передаем полное имя, например, 'сибирцево'
        )

        if distance_result is not None and int(distance_result) > 0:
            distance_int = int(distance_result)
            logger.info(f"✅ [Tariff] Расстояние получено: {from_station_name} -> {to_station_name} = {distance_int} км.")
            return distance_int
        else:
            # Лог о том, что не найдено, теперь выводится из get_distance_sync
            logger.info(f"[Tariff] Расстояние не найдено (ядро вернуло 0 или None) для {from_station_name} -> {to_station_name}.")
            return None

    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при вызове zdtarif_bot: {e}", exc_info=True)
        return None