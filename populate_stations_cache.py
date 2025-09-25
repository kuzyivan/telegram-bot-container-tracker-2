# populate_stations_cache.py
import asyncio
from sqlalchemy import select
from db import SessionLocal
from models import Tracking
from services.osm_service import fetch_station_coords
from logger import get_logger

logger = get_logger("station_cacher")

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
    """Основная логика кеширования, которую будет вызывать планировщик."""
    logger.info("--- 🏁 [Scheduler] Запуск задачи кеширования станций ---")
    
    stations_to_find = await get_unique_stations_from_tracking()
    
    if not stations_to_find:
        logger.info("[Scheduler] Нет новых станций для поиска. Завершение.")
        return

    success_count = 0
    fail_count = 0

    for station_name in stations_to_find:
        try:
            coords = await fetch_station_coords(station_name)
            if coords:
                success_count += 1
            else:
                logger.warning(f"❌ [Cacher] Не удалось найти координаты для станции: {station_name}")
                fail_count += 1
            await asyncio.sleep(1) # Задержка между запросами
        except Exception as e:
            logger.error(f"[Cacher] Критическая ошибка при обработке станции '{station_name}': {e}", exc_info=True)
            fail_count += 1

    logger.info("--- ✅ [Scheduler] Задача кеширования станций завершена ---")
    logger.info(f"  - Успешно обработано (найдено или уже в кеше): {success_count}")
    logger.info(f"  - Не удалось найти: {fail_count}")

# Этот блок позволяет запускать скрипт вручную для отладки
if __name__ == "__main__":
    asyncio.run(job_populate_stations_cache())