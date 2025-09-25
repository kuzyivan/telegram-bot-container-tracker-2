# populate_stations_cache.py
import asyncio
from sqlalchemy import select, func
from db import SessionLocal
from models import Tracking
from services.osm_service import fetch_station_coords
from logger import get_logger

logger = get_logger("station_cacher")

async def get_unique_stations_from_tracking() -> set[str]:
    """Собирает все уникальные названия станций из таблицы дислокации."""
    unique_stations = set()
    async with SessionLocal() as session:
        # distinct() здесь не работает как ожидалось с async, делаем вручную
        from_stations_result = await session.execute(select(Tracking.from_station))
        to_stations_result = await session.execute(select(Tracking.to_station))
        current_stations_result = await session.execute(select(Tracking.current_station))

        for row in from_stations_result.scalars().all():
            if row: unique_stations.add(row)
        for row in to_stations_result.scalars().all():
            if row: unique_stations.add(row)
        for row in current_stations_result.scalars().all():
            if row: unique_stations.add(row)
            
    logger.info(f"Найдено {len(unique_stations)} уникальных станций в таблице 'tracking'.")
    return unique_stations

async def main():
    """Главная функция для запуска процесса кеширования."""
    logger.info("--- 🏁 Запуск процесса кеширования станций ---")
    
    stations_to_find = await get_unique_stations_from_tracking()
    
    if not stations_to_find:
        logger.info("Нет станций для поиска. Завершение.")
        return

    success_count = 0
    fail_count = 0

    for station_name in stations_to_find:
        try:
            # fetch_station_coords уже содержит логику 'не искать, если есть в кеше'
            coords = await fetch_station_coords(station_name)
            if coords:
                logger.info(f"✅ Успешно найдена (или уже в кеше) станция: {station_name}")
                success_count += 1
            else:
                logger.warning(f"❌ Не удалось найти координаты для станции: {station_name}")
                fail_count += 1
            
            # Добавляем небольшую задержку, чтобы не перегружать Overpass API
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Критическая ошибка при обработке станции '{station_name}': {e}", exc_info=True)
            fail_count += 1

    logger.info("--- ✅ Процесс кеширования станций завершен ---")
    logger.info(f"  - Успешно обработано: {success_count}")
    logger.info(f"  - Не удалось найти: {fail_count}")

if __name__ == "__main__":
    asyncio.run(main())