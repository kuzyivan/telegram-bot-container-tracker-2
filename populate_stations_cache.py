# populate_stations_cache.py
import asyncio
from sqlalchemy import select, func, distinct
from sqlalchemy.dialects.postgresql import insert

from db import SessionLocal
# ✅ Исправляем импорт RailwayStation -> StationsCache
from models import Tracking, StationsCache 
from services.osm_service import OsmService
from logger import get_logger
import config

logger = get_logger(__name__)

async def get_unique_stations_from_tracking() -> set[str]:
    """Получает уникальные названия станций (отправления, назначения, текущие) из таблицы tracking."""
    unique_stations = set()
    async with SessionLocal() as session:
        # Выбираем уникальные непустые значения из трех колонок
        columns_to_check = [Tracking.from_station, Tracking.to_station, Tracking.current_station]
        for column in columns_to_check:
            result = await session.execute(select(distinct(column)).where(column != None, column != ''))
            stations = result.scalars().all()
            unique_stations.update(stations)
    # Убираем None или пустые строки, если они как-то попали
    unique_stations = {s for s in unique_stations if s} 
    logger.info(f"Найдено {len(unique_stations)} уникальных станций в таблице 'tracking'.")
    return unique_stations

async def get_existing_cached_stations() -> set[str]:
    """Получает множество оригинальных имен станций, уже имеющихся в кеше."""
    async with SessionLocal() as session:
        result = await session.execute(select(StationsCache.original_name)) # ✅ Используем StationsCache
        existing_names = set(result.scalars().all())
        logger.info(f"В кеше уже есть {len(existing_names)} станций.")
        return existing_names

async def populate_stations_cache_job():
    """Основная задача: находит новые станции и кеширует их координаты из OSM."""
    logger.info("--- 🏁 Запуск процесса кеширования станций ---")

    try:
        unique_station_names = await get_unique_stations_from_tracking()
        existing_cached_names = await get_existing_cached_stations()

        new_station_names = list(unique_station_names - existing_cached_names)

        if not new_station_names:
            logger.info("--- ✅ Новых станций для кеширования не найдено ---")
            return

        logger.info(f"Нужно найти {len(new_station_names)} новых станций.")

        osm_service = OsmService()
        processed_count = 0
        not_found_count = 0

        async with SessionLocal() as session:
            for i, station_name in enumerate(new_station_names):
                logger.info(f"--- Обработка {i+1}/{len(new_station_names)}: '{station_name}' ---")

                coords = await osm_service.get_station_coordinates(station_name) # Эта функция уже кеширует результат

                if coords:
                    processed_count += 1
                    # Дополнительно убедимся, что запись создана, если get_station_coordinates не сделала это
                    # (хотя она должна была)
                    insert_stmt = insert(StationsCache).values( # ✅ Используем StationsCache
                        original_name=station_name,
                        # found_name - устанавливается внутри get_station_coordinates
                        latitude=coords.lat,
                        longitude=coords.lon
                    ).on_conflict_do_nothing(index_elements=['original_name']) # Не перезаписываем, если уже есть
                    await session.execute(insert_stmt)

                else:
                    not_found_count += 1
                    # Создаем запись в кеше без координат, чтобы не искать повторно
                    insert_stmt = insert(StationsCache).values( # ✅ Используем StationsCache
                        original_name=station_name,
                        found_name=None,
                        latitude=None,
                        longitude=None
                    ).on_conflict_do_nothing(index_elements=['original_name'])
                    await session.execute(insert_stmt)
                    logger.warning(f"   -> Координаты для '{station_name}' не найдены.")

                await session.commit() # Коммит после каждой станции
                await asyncio.sleep(1) # Небольшая пауза

        logger.info("--- ✅ Процесс кеширования станций завершен ---")
        logger.info(f"   - Успешно обработано: {processed_count}")
        logger.info(f"   - Не удалось найти: {not_found_count}")

    except Exception as e:
        logger.error(f"❌ Ошибка в процессе кеширования станций: {e}", exc_info=True)

# Функция для вызова из scheduler.py
async def job_populate_stations_cache():
    if config.STATIONS_CACHE_CRON_SCHEDULE: # Проверяем, включена ли задача в конфиге
         await populate_stations_cache_job()
    else:
        logger.info("Плановое кеширование станций отключено в конфигурации.")

# # Для ручного запуска:
# if __name__ == "__main__":
#     asyncio.run(populate_stations_cache_job())