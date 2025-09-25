# populate_stations_cache.py
import asyncio
import re
from sqlalchemy import select
from db import SessionLocal
from models import Tracking, RailwayStation # <--- Добавляем RailwayStation
from services.osm_service import fetch_station_coords, get_canonical_name # <--- Импортируем новые функции

logger = get_logger("station_cacher")

def generate_name_variations(station_name: str) -> list[str]:
    # ... (код этой функции остается без изменений) ...
    name = re.sub(r'\s*\(\d+\)$', '', station_name).strip()
    suffixes_to_remove = ["ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ", "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ", "ЭКСП", "ПАРК"]
    base_name = name
    for suffix in suffixes_to_remove:
        base_name = re.sub(r'[\s-]+' + re.escape(suffix) + r'\b', '', base_name, flags=re.IGNORECASE)
    base_name = base_name.strip()
    variations = {base_name}
    match = re.search(r'(.+?)[\s-]*((?:[IVX]+)|(?:[0-9]+))$', base_name)
    if match:
        name_part, num_part = match.group(1).strip(), match.group(2)
        arabic, roman = "", ""
        if num_part.isdigit():
            arabic = num_part
            roman_map = {'1': 'I', '2': 'II', '3': 'III', '4': 'IV'}
            roman = roman_map.get(arabic, "")
        else:
            roman = num_part
            roman_map_rev = {'I': '1', 'II': '2', 'III': '3', 'IV': '4'}
            arabic = roman_map_rev.get(roman, "")
        variations.add(name_part)
        if arabic:
            variations.add(f"{name_part}-{arabic}")
            variations.add(f"{name_part} {arabic}")
        if roman:
            variations.add(f"{name_part}-{roman}")
            variations.add(f"{name_part} {roman}")
    return sorted(list(variations), key=len, reverse=True)


async def get_unique_stations_from_tracking() -> set[str]:
    # ... (код без изменений) ...
    # ...
    pass # Заглушка

async def job_populate_stations_cache():
    """Основная логика кеширования с предварительной проверкой кеша."""
    logger.info("--- 🏁 Запуск процесса кеширования станций (с проверкой кеша) ---")
    
    all_stations_from_db = await get_unique_stations_from_tracking()
    
    # --- НОВАЯ ЛОГИКА ---
    # 1. Получаем все станции, которые уже есть в кеше
    async with SessionLocal() as session:
        result = await session.execute(select(RailwayStation.name))
        stations_in_cache = {row[0] for row in result}
    logger.info(f"В кеше уже есть {len(stations_in_cache)} станций.")

    # 2. Определяем, какие станции нужно искать
    stations_to_find = []
    for station_name in all_stations_from_db:
        canonical_name = get_canonical_name(station_name)
        if canonical_name not in stations_in_cache:
            stations_to_find.append(station_name)
    
    logger.info(f"Нужно найти {len(stations_to_find)} новых станций.")
    # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

    if not stations_to_find:
        logger.info("Нет станций для поиска. Завершение.")
        return

    success_count = 0
    fail_count = 0
    
    stations_to_find_sorted = sorted(stations_to_find)
    for i, original_name in enumerate(stations_to_find_sorted):
        logger.info(f"--- Обработка {i+1}/{len(stations_to_find_sorted)}: '{original_name}' ---")
        
        name_variations = generate_name_variations(original_name)
        logger.info(f"Сгенерированы варианты: {name_variations}")
        
        coords = None
        for name_variant in name_variations:
            # Передаем и вариант для поиска, и оригинал для кеширования
            coords = await fetch_station_coords(name_variant, original_name)
            if coords:
                logger.info(f"✅ Найдено по варианту: '{name_variant}'")
                break 
            await asyncio.sleep(1)
        
        if coords:
            success_count += 1
        else:
            logger.warning(f"❌ [Cacher] Не удалось найти координаты для станции: {original_name}")
            fail_count += 1
        
        await asyncio.sleep(2)

    logger.info("--- ✅ Процесс кеширования станций завершен ---")
    logger.info(f"  - Успешно обработано: {success_count}")
    logger.info(f"  - Не удалось найти: {fail_count}")

if __name__ == "__main__":
    # ... (код без изменений) ...
    # ...
    pass # Заглушка