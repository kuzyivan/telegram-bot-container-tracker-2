# populate_stations_cache.py
import asyncio
import re
from sqlalchemy import select
from db import SessionLocal
from models import Tracking
from services.osm_service import fetch_station_coords
from logger import get_logger

logger = get_logger("station_cacher")

# --- УЛУЧШЕННАЯ ЛОГИКА ОЧИСТКИ ---
def simplify_station_name(station_name: str) -> str:
    """Упрощает название станции для более гибкого поиска в OSM."""
    # 1. Убираем код станции
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip()
    # 2. Убираем слова-уточнения
    suffixes_to_remove = [
        "ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ",
        "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ"
    ]
    for suffix in suffixes_to_remove:
        name = re.sub(r'[\s-]+' + suffix, '', name, flags=re.IGNORECASE)
    # 3. Заменяем арабские цифры на римские для станций типа "КУНЦЕВО 2" -> "КУНЦЕВО II"
    name = name.replace(" 2", " II").replace(" 1", " I")
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
    logger.info("--- 🏁 Запуск процесса кеширования станций (улучшенная версия) ---")
    
    all_stations = await get_unique_stations_from_tracking()
    stations_to_find = sorted(list(all_stations)) # Сортируем для предсказуемости
    
    if not stations_to_find:
        logger.info("Нет станций для поиска. Завершение.")
        return

    success_count = 0
    fail_count = 0
    
    # --- УЛУЧШЕННЫЙ ЦИКЛ ОБРАБОТКИ ---
    for i, original_name in enumerate(stations_to_find):
        logger.info(f"--- Обработка {i+1}/{len(stations_to_find)}: '{original_name}' ---")
        try:
            # Сначала пытаемся найти по оригинальному "чистому" имени
            coords = await fetch_station_coords(original_name)
            
            # Если не нашли, пытаемся найти по упрощенному имени
            if not coords:
                simplified = simplify_station_name(original_name)
                if simplified.lower() != original_name.split('(')[0].strip().lower():
                    logger.info(f"Попытка #2: поиск по упрощенному имени '{simplified}'")
                    coords = await fetch_station_coords(simplified)

            if coords:
                success_count += 1
            else:
                logger.warning(f"❌ [Cacher] Не удалось найти координаты для станции: {original_name}")
                fail_count += 1
            
            # УВЕЛИЧИВАЕМ ЗАДЕРЖКУ, чтобы быть "вежливее" к серверу
            await asyncio.sleep(2) 

        except Exception as e:
            logger.error(f"[Cacher] Критическая ошибка при обработке станции '{original_name}': {e}", exc_info=True)
            fail_count += 1

    logger.info("--- ✅ Процесс кеширования станций завершен ---")
    logger.info(f"  - Успешно обработано: {success_count}")
    logger.info(f"  - Не удалось найти: {fail_count}")

if __name__ == "__main__":
    asyncio.run(job_populate_stations_cache())