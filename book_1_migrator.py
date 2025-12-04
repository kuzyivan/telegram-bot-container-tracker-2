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

# Подгружаем модели из централизованного файла models.py
from models import RailwaySection
from db_base import Base 

# Настройка
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

DATA_DIR = "zdtarif_bot/data" # Путь к твоим CSV

async def migrate_book_1():
    if not TARIFF_DB_URL:
        logger.error("Не задан TARIFF_DATABASE_URL. Проверьте файл .env")
        return

    engine = create_async_engine(TARIFF_DB_URL, echo=False)
    
    # 1. Создаем таблицу (если нет), используя правильный Base
    async with engine.begin() as conn:
        logger.info(f"Проверка и создание таблицы {RailwaySection.__tablename__}...")
        await conn.run_sync(Base.metadata.create_all, tables=[RailwaySection.__table__])
        
        # Очищаем старые данные перед импортом
        logger.info(f"Очистка таблицы {RailwaySection.__tablename__}...")
        await conn.execute(text(f"TRUNCATE TABLE {RailwaySection.__tablename__} RESTART IDENTITY CASCADE"))

    Session = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Ищем файлы
    files = sorted(glob.glob(os.path.join(DATA_DIR, "1-*.csv")))
    logger.info(f"Найдено файлов Книги 1: {len(files)}")

    for filepath in files:
        filename = os.path.basename(filepath)
        logger.info(f"Обработка файла: {filename}")
        
        try:
            # ✅ Используем кодировку UTF-8 и читаем все строки
            df = pd.read_csv(filepath, header=None, encoding='utf-8', dtype=str, on_bad_lines='skip')
            
            current_section_stations = []
            sections_to_save = []
            
            for index, row in df.iterrows():
                # Пропускаем короткие/неполные строки
                if len(row) < 3:
                    continue

                raw_code = str(row[1]) if pd.notna(row[1]) else ""
                raw_name = str(row[2]) if pd.notna(row[2]) else ""
                
                # ✅ Очищаем код от всего, кроме цифр
                clean_code = re.sub(r'[^\d]', '', raw_code)
                
                # Проверяем на валидный код станции
                if re.fullmatch(r'\d{5,6}', clean_code):
                    station_obj = {
                        "c": clean_code, 
                        "n": raw_name.strip()
                    }
                    current_section_stations.append(station_obj)
                else:
                    # Разрыв в данных, сохраняем предыдущий участок, если он валиден
                    if len(current_section_stations) > 1:
                        sections_to_save.append(list(current_section_stations))
                    # Сбрасываем для нового участка
                    current_section_stations = []
            
            # Сохраняем последний участок, если он остался после цикла
            if len(current_section_stations) > 1:
                sections_to_save.append(current_section_stations)

            # 3. Сохраняем в БД
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
                
                logger.info(f"   -> Найдено и сохранено {len(sections_to_save)} сегментов.")
            else:
                logger.warning(f"   -> В файле {filename} не найдено последовательностей станций.")

        except Exception as e:
            logger.error(f"Ошибка при обработке {filename}: {e}")

    await engine.dispose()
    logger.info("🎉 Импорт данных из Книги 1 завершен!")

if __name__ == "__main__":
    asyncio.run(migrate_book_1())
