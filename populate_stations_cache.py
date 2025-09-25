# populate_stations_cache.py
import asyncio
import re
from sqlalchemy import select, text
from db import SessionLocal
from models import Tracking
from services.osm_service import fetch_station_coords
from logger import get_logger

logger = get_logger("station_cacher")

def simplify_station_name(station_name: str) -> str:
    """
    Упрощает название станции, убирая общие суффиксы и нормализуя пробелы/дефисы.
    """
    # 1. Убираем код станции в скобках
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip()
    
    # 2. Список суффиксов и слов-уточнений для удаления
    suffixes_to_remove = [
        "ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ",
        "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ",
        "ЭКСП", "ПАРК"
    ]
    for suffix in suffixes_to_remove:
        name = re.sub(r'[\s-]+' + re.escape(suffix) + r'\b', '', name, flags=re.IGNORECASE)

    # 3. Нормализуем пробелы вокруг цифр и дефисов
    # Например, "ДАЛЬНЕРЕЧЕНСК 2" -> "ДАЛЬНЕРЕЧЕНСК-2"
    name = re.sub(r'\s+([1-9])$', r'-\1', name)
    
    return name.strip()


async def get_unique_stations_from_tracking() -> set[str]:
    """Собирает все уникальные названия станций из таблицы дислокации."""
    unique_stations = set()
    async with SessionLocal() as session:
        from_stations_result = await session.execute(select(Tracking.from_station).distinct())
        to_stations_result = await session.execute(select(Tracking.to_station).distinct())
        current_stations_result = await session.execute(select(Tracking.current_station).distinct())

        for row in from_stations_result.scalars().all():
            if row: unique_stations.add(row)
        for row in to_stations_result.scalars().all():
            if row: unique_stations.add(row)
        for row in current_stations_result.scalars().all():
            if row: unique_stations.add(row)
            
    logger.info(f"Найдено {len(unique_stations)} уникальных станций в таблице 'tracking'.")
    return unique_stations

async def job_populate_stations_cache():
    """Основная логика кеширования с улучшенной обработкой имён и задержками."""
    logger.info("--- 🏁 Запуск процесса кеширования станций (финальная версия) ---")
    
    all_stations = await get_unique_stations_from_tracking()
    stations_to_find = sorted(list(all_stations))
    
    if not stations_to_find:
        logger.info("Нет станций для поиска. Завершение.")
        return

    success_count = 0
    fail_count = 0
    
    for i, original_name in enumerate(stations_to_find):
        logger.info(f"--- Обработка {i+1}/{len(stations_to_find)}: '{original_name}' ---")
        try:
            # Сразу ищем по максимально упрощенному имени - это самый надежный способ
            simplified = simplify_station_name(original_name)
            coords = await fetch_station_coords(simplified)

            # Если не нашли, на всякий случай попробуем по базовому чистому имени
            if not coords:
                base_clean_name = re.sub(r'\s*\(\d+\)$', '', original_name).strip()
                if simplified.lower() != base_clean_name.lower():
                    logger.info(f"Попытка #2: поиск по базовому имени '{base_clean_name}'")
                    coords = await fetch_station_coords(base_clean_name)

            if coords:
                success_count += 1
            else:
                logger.warning(f"❌ [Cacher] Не удалось найти координаты для станции: {original_name} (искали как '{simplified}')")
                fail_count += 1
            
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"[Cacher] Критическая ошибка при обработке станции '{original_name}': {e}", exc_info=True)
            fail_count += 1

    logger.info("--- ✅ Процесс кеширования станций завершен ---")
    logger.info(f"  - Успешно обработано: {success_count}")
    logger.info(f"  - Не удалось найти: {fail_count}")

if __name__ == "__main__":
    asyncio.run(job_populate_stations_cache())