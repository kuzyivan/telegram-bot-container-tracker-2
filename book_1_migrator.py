# book_1_migrator.py
import asyncio
import os
import glob
import pandas as pd
import re
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from dotenv import load_dotenv

# Подгружаем модели
from services.tariff_service import RailwaySection, TariffBase

# Настройка
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

DATA_DIR = "zdtarif_bot/data" 

async def migrate_book_1():
    if not TARIFF_DB_URL:
        logger.error("Не задан TARIFF_DATABASE_URL")
        return

    logger.info("Проверка и создание таблицы railway_sections...")
    engine = create_async_engine(TARIFF_DB_URL, echo=False)
    
    # 1. Создаем таблицу
    async with engine.begin() as conn:
        await conn.run_sync(TariffBase.metadata.create_all)
        logger.info("Очистка таблицы railway_sections...")
        await conn.execute(text("TRUNCATE TABLE railway_sections RESTART IDENTITY CASCADE"))

    Session = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Ищем файлы
    files = glob.glob(os.path.join(DATA_DIR, "1-*.csv"))
    logger.info(f"Найдено файлов Книги 1: {len(files)}")

    for filepath in files:
        filename = os.path.basename(filepath)
        logger.info(f"Обработка файла: {filename}")
        
        try:
            # ✅ ИСПРАВЛЕНИЕ: Вернули cp1251
            df = pd.read_csv(filepath, header=None, encoding='cp1251', dtype=str, sep=',') 
            # sep=',' важно, если вдруг там точка с запятой, но обычно запятая
            
            current_section_stations = []
            sections_to_save = []
            
            for index, row in df.iterrows():
                # Индексы колонок могут смещаться, если разделитель не тот.
                # Обычно: 0-№, 1-Код, 2-Имя
                # Берем данные безопасно
                raw_code = str(row[1]) if len(row) > 1 and pd.notna(row[1]) else ""
                raw_name = str(row[2]) if len(row) > 2 and pd.notna(row[2]) else ""
                
                # Очистка кода от мусора
                clean_code = re.sub(r'[^\d]', '', raw_code)
                
                # Проверка валидности кода (5 или 6 цифр)
                if re.fullmatch(r'\d{5,6}', clean_code):
                    
                    station_obj = {
                        "c": clean_code, 
                        "n": raw_name.strip()
                    }
                    current_section_stations.append(station_obj)
                
                else:
                    # Разрыв (заголовок или пустая строка) -> сохраняем накопленное
                    if len(current_section_stations) > 1:
                        sections_to_save.append(list(current_section_stations))
                    
                    current_section_stations = []
            
            # Хвост
            if len(current_section_stations) > 1:
                sections_to_save.append(current_section_stations)

            # 3. Сохранение в БД
            if sections_to_save:
                async with Session() as session:
                    async with session.begin():
                        for section in sections_to_save:
                            start_node = section[0]['c']
                            end_node = section[-1]['c']
                            
                            db_obj = RailwaySection(
                                node_start_code=start_node,
                                node_end_code=end_node,
                                source_file=filename,
                                stations_list=section
                            )
                            session.add(db_obj)
                # logger.info(f"   -> Сохранено {len(sections_to_save)} сегментов.")
            else:
                logger.warning(f"   -> В файле {filename} не найдено последовательностей станций.")

        except Exception as e:
            logger.error(f"Ошибка при обработке {filename}: {e}")

    await engine.dispose()
    logger.info("🎉 Импорт данных из Книги 1 завершен!")

if __name__ == "__main__":
    asyncio.run(migrate_book_1())