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
from models import RailwaySection
from db_base import Base 

# Настройка
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
# ВАЖНО: Убедитесь, что в .env файле есть переменная TARIFF_DATABASE_URL
# Пример: TARIFF_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/tariff_db
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

DATA_DIR = "zdtarif_bot/data" # Путь к CSV файлам

async def migrate_book_1():
    if not TARIFF_DB_URL:
        logger.error("Переменная окружения TARIFF_DATABASE_URL не задана. Проверьте .env файл.")
        return

    engine = create_async_engine(TARIFF_DB_URL, echo=False)
    
    # 1. Создаем таблицу (если она не существует)
    async with engine.begin() as conn:
        logger.info(f"Проверка и создание таблицы {RailwaySection.__tablename__}...")
        await conn.run_sync(Base.metadata.create_all, tables=[RailwaySection.__table__])
        
        # Очищаем старые данные перед импортом
        logger.info(f"Очистка таблицы {RailwaySection.__tablename__}...")
        await conn.execute(text(f"TRUNCATE TABLE {RailwaySection.__tablename__} RESTART IDENTITY CASCADE"))

    Session = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Ищем файлы Книги 1
    files = sorted(glob.glob(os.path.join(DATA_DIR, "1-*.csv")))
    logger.info(f"Найдено файлов Книги 1: {len(files)}")

    for filepath in files:
        filename = os.path.basename(filepath)
        logger.info(f"Обработка файла: {filename}")
        
        try:
            # Используем pandas для чтения CSV.
            # skiprows=5 - это предположение, возможно, придется подобрать.
            # encoding='cp1251' - стандарт для старых ж/д документов.
            df = pd.read_csv(filepath, skiprows=5, encoding='cp1251', header=None, dtype=str, on_bad_lines='warn')
            
            current_section_stations = []
            sections_to_save = []
            
            for index, row in df.iterrows():
                # Пропускаем строки, где меньше 3 колонок
                if len(row) < 3:
                    continue
                
                # Извлекаем код и имя, обрабатываем возможные пустые значения (NaN)
                raw_code = str(row[1]).strip() if pd.notna(row[1]) else ""
                raw_name = str(row[2]).strip() if pd.notna(row[2]) else ""
                
                # Проверяем, похож ли код на код станции (5 или 6 цифр)
                if re.fullmatch(r'\d{5,6}', raw_code):
                    station_obj = {
                        "c": raw_code, # 'c' for code
                        "n": raw_name  # 'n' for name
                    }
                    current_section_stations.append(station_obj)
                else:
                    # Если строка не похожа на станцию, это разрыв.
                    # Если в текущем списке больше одной станции, сохраняем его как участок.
                    if len(current_section_stations) > 1:
                        sections_to_save.append(list(current_section_stations))
                    
                    # Сбрасываем список для нового участка
                    current_section_stations = []
            
            # После окончания цикла, если в списке остались станции, это последний участок
            if len(current_section_stations) > 1:
                sections_to_save.append(current_section_stations)

            # 3. Сохраняем найденные участки в базу данных
            if sections_to_save:
                async with Session() as session:
                    async with session.begin():
                        for section_list in sections_to_save:
                            # Первая и последняя станции участка
                            start_node_code = section_list[0]['c']
                            end_node_code = section_list[-1]['c']
                            
                            db_obj = RailwaySection(
                                node_start_code=start_node_code,
                                node_end_code=end_node_code,
                                source_file=filename,
                                stations_list=section_list
                            )
                            session.add(db_obj)
                
                logger.info(f"   -> Найдено и сохранено {len(sections_to_save)} участков.")
            else:
                logger.warning(f"   -> В файле {filename} не найдено последовательностей станций.")

        except FileNotFoundError:
            logger.error(f"Файл не найден: {filepath}")
        except Exception as e:
            logger.error(f"Ошибка при обработке файла {filename}: {e}")

    await engine.dispose()
    logger.info("🎉 Импорт данных из Книги 1 завершен!")

if __name__ == "__main__":
    # Для запуска этого скрипта:
    # 1. Убедитесь, что у вас установлен pandas: pip install pandas
    # 2. Убедитесь, что в файле .env указана переменная TARIFF_DATABASE_URL
    # 3. Выполните в терминале: python book_1_migrator.py
    asyncio.run(migrate_book_1())
