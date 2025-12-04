import asyncio
import logging
import aiohttp
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from dotenv import load_dotenv

# Импортируем нашу новую модель и Base
from services.tariff_service import StationCoordinate, TariffBase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OSM_Seeder")

load_dotenv()
# В оригинальном коде была TARIFF_DATABASE_URL, но основной DATABASE_URL тот же
# и используется для всех моделей. Для согласованности использую его.
DB_URL = os.getenv("TARIFF_DATABASE_URL")

# Запрос к Overpass API:
# Ищем узлы (node) в зоне "Russia" (код 60189), 
# которые являются жд станциями (railway=station) 
# и имеют тег 'esr:user' или 'ref:esr' (код ЕСР).
OVERPASS_QUERY = """
[out:json][timeout:90];
area["name:en"="Russia"]->.searchArea;
(
  node["railway"="station"]["esr:user"](area.searchArea);
  node["railway"="station"]["ref:esr"](area.searchArea);
);
out body;
"""

async def seed_coordinates():
    if not DB_URL:
        logger.error("Переменная окружения TARIFF_DATABASE_URL не установлена! Не могу подключиться к БД.")
        return

    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # 1. Создаем таблицу, если ее нет.
    # Alembic — лучший способ управления миграциями, но для простого 
    # скрипта-сидера create_all() тоже подойдет.
    async with engine.begin() as conn:
        logger.info("Проверяем/создаем таблицу 'station_coordinates'...")
        await conn.run_sync(TariffBase.metadata.create_all, tables=[StationCoordinate.__table__])
    
    # 2. Качаем данные с OSM
    logger.info("📡 Скачиваем данные из OpenStreetMap (Overpass API)...")
    async with aiohttp.ClientSession() as http:
        # Используем публичный инстанс maps.mail.ru, он стабилен
        async with http.post("https://maps.mail.ru/osm/tools/overpass/api/interpreter", data=OVERPASS_QUERY) as resp:
            if resp.status != 200:
                logger.error(f"Ошибка API Overpass: {resp.status}")
                text_err = await resp.text()
                logger.error(f"Ответ сервера: {text_err}")
                return
            
            data = await resp.json()

    elements = data.get("elements", [])
    if not elements:
        logger.warning("Не удалось получить станции из OSM. Возможно, API временно недоступен.")
        return
        
    logger.info(f"✅ Получено {len(elements)} станций с кодами ЕСР.")

    # 3. Сохраняем в БД
    async with Session() as session:
        counter = 0
        upserted_count = 0
        new_count = 0
        
        logger.info("Начинаем загрузку/обновление координат в базе данных...")
        for el in elements:
            tags = el.get("tags", {})
            
            # Достаем код ЕСР (он может быть в разных тегах)
            esr = tags.get("esr:user") or tags.get("ref:esr")
            
            if not esr or not esr.isdigit() or len(esr) < 5: 
                continue

            # Код должен быть строкой из 6 цифр, дополняем нулями, если нужно.
            # В тарифах коды шестизначные.
            esr = esr.strip().zfill(6)
            
            lat = el.get("lat")
            lon = el.get("lon")
            name = tags.get("name")

            if not lat or not lon:
                continue

            # Upsert (вставить или обновить)
            existing = await session.get(StationCoordinate, esr)
            if existing:
                existing.lat = lat
                existing.lon = lon
                if name: existing.name = name
                upserted_count +=1
            else:
                new_st = StationCoordinate(code=esr, lat=lat, lon=lon, name=name)
                session.add(new_st)
                new_count += 1
            
            counter += 1
            if counter % 1000 == 0:
                logger.info(f"Обработано {counter} из {len(elements)}...")
        
        await session.commit()
    
    logger.info(f"🎉 Готово! Всего обработано: {counter}. Новых: {new_count}. Обновлено: {upserted_count}.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_coordinates())
