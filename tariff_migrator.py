# tariff_migrator.py
import asyncio
import os
import re
import pandas as pd
import sys
import glob # <-- Важный импорт
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
import logging

# --- 1. Настройка логгирования и .env ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Добавляем корень проекта в sys.path, чтобы найти zdtarif_bot/data
current_file_path = os.path.abspath(__file__)
project_root_dir = os.path.dirname(current_file_path)
sys.path.insert(0, project_root_dir)

# Загружаем переменные окружения (особенно TARIFF_DATABASE_URL)
load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

# --- 2. Определение ORM Моделей для новой БД ---

class Base(DeclarativeBase):
    pass

class TariffStation(Base):
    '''
    Таблица для хранения данных из 2-РП.csv.
    '''
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True, unique=True) 
    code: Mapped[str] = mapped_column(String(6), index=True) 
    railway: Mapped[str | None] = mapped_column(String)
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String)) 

    __table_args__ = (
        Index('ix_tariff_stations_name_code', 'name', 'code'),
    )

class TariffMatrix(Base):
    '''
    Таблица для хранения данных из 3-*.csv.
    '''
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )

# --- 3. Вспомогательные функции парсинга ---

def parse_transit_points_for_db(tp_string: str) -> list[str]:
    '''
    Парсит строку транзитных пунктов из 2-РП.csv и возвращает список строк.
    '''
    if not isinstance(tp_string, str) or not tp_string:
        return []
    
    pattern = re.compile(r'(\d{6})\s(.*?)\s-\s(\d+)км')
    matches = pattern.findall(tp_string)
    
    transit_points_str = []
    for match in matches:
        transit_points_str.append(f"{match[0]}:{match[1].strip()}:{int(match[2])}")
        
    return transit_points_str

def load_kniga_2_rp(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает 2-РП.csv из zdtarif_bot/data
    '''
    try:
        df = pd.read_csv(
            filepath,
            skiprows=6, # Пропускаем заголовки
            names=[
                'num', 'station_name', 'operations', 'railway', 
                'transit_points_raw', 'station_code'
            ],
            encoding='cp1251',
            dtype={'station_code': str} 
        )
        df['station_name'] = df['station_name'].str.strip()
        df['station_code'] = df['station_code'].str.strip()
        df['railway'] = df['railway'].str.strip()
        df.dropna(subset=['station_name', 'station_code'], inplace=True)
        df.drop_duplicates(subset=['station_name'], keep='first', inplace=True)
        
        log.info(f"✅ Файл {os.path.basename(filepath)} загружен, {len(df)} УНИКАЛЬНЫХ станций.")
        return df
    except FileNotFoundError:
        log.error(f"❌ Ошибка: Не найден файл '{filepath}'.")
        return None
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке {filepath}: {e}", exc_info=True)
        return None

def load_kniga_3_matrix(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает матрицу (3-*.csv) и преобразует ее в "длинный" формат.
    '''
    try:
        df = pd.read_csv(filepath, skiprows=6, encoding='cp1251') # Пропускаем заголовки
        
        df.iloc[:, 1] = df.iloc[:, 1].astype(str).str.strip()
        df = df.set_index(df.columns[1])
        df = df.drop(columns=[df.columns[0]]) # Удаляем '№ п/п'
        
        df.columns = df.columns.str.strip()

        # --- 🐞 ИСПРАВЛЕНИЕ (ValueError: dropna must be unspecified) 🐞 ---
        df_long = df.stack(future_stack=True).reset_index() 
        # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
        
        df_long.columns = ['station_a', 'station_b', 'distance']
        
        df_long = df_long[pd.to_numeric(df_long['distance'], errors='coerce').notna()]
        df_long['distance'] = df_long['distance'].astype(int)
        
        df_long = df_long[df_long['distance'] > 0]
        
        df_long.drop_duplicates(subset=['station_a', 'station_b'], keep='first', inplace=True)
        
        log.info(f"✅ Матрица {os.path.basename(filepath)} загружена, {len(df_long)} УНИКАЛЬНЫХ маршрутов.")
        return df_long
    except FileNotFoundError:
        log.error(f"❌ Ошибка: Не найден файл '{filepath}'.")
        return None
    except Exception as e:
        log.error(f"❌ Ошибка при обработке матрицы {filepath}: {e}", exc_info=True)
        return None

# --- 4. Основная функция миграции ---

async def main_migrate():
    '''
    Главная функция. Подключается, создает таблицы, загружает данные.
    '''
    if not TARIFF_DB_URL:
        log.error("❌ TARIFF_DATABASE_URL не найдена в .env файле. Миграция отменена.")
        return
        
    log.info(f"Подключение к новой базе данных тарифов: {TARIFF_DB_URL.split('@')[-1]}")
    
    # 1. Создаем движок и таблицы
    engine = create_async_engine(TARIFF_DB_URL)
    async with engine.begin() as conn:
        log.info("Очистка существующих таблиц (если есть)...")
        await conn.run_sync(Base.metadata.drop_all)
        log.info("Создание новых таблиц (tariff_stations, tariff_matrix)...")
        await conn.run_sync(Base.metadata.create_all)
    
    Session = async_sessionmaker(engine, expire_on_commit=False)
    
    # 2. Миграция станций (2-РП.csv)
    log.info("--- 1/2: Начинаю миграцию Станций (2-РП.csv) ---")
    data_dir_path = os.path.join(project_root_dir, 'zdtarif_bot', 'data')
    stations_df = load_kniga_2_rp(os.path.join(data_dir_path, '2-РП.csv'))
    
    if stations_df is not None:
        async with Session() as session:
            async with session.begin():
                stations_to_add = []
                for _, row in stations_df.iterrows():
                    stations_to_add.append(
                        TariffStation(
                            name=row['station_name'],
                            code=row['station_code'],
                            railway=row['railway'],
                            transit_points=parse_transit_points_for_db(row['transit_points_raw'])
                        )
                    )
                log.info(f"Добавляю {len(stations_to_add)} станций в базу...")
                session.add_all(stations_to_add)
            await session.commit()
        log.info("✅ Миграция станций завершена.")
    else:
        log.error("❌ Миграция станций провалена, файл не загружен.")
        return

    # --- 🐞 ИЗМЕНЕНИЕ: Загрузка ВСЕХ матриц 🐞 ---
    
    log.info("--- 2/2: Начинаю миграцию ВСЕХ Матриц (3-*.csv) ---")
    
    # Ищем ВСЕ файлы матриц 3-
    matrix_files = glob.glob(os.path.join(data_dir_path, '3-*.csv'))
    
    if not matrix_files:
        log.error("❌ Не найдено ни одного файла матриц (3-*.csv) в zdtarif_bot/data/")
        return

    total_routes_added = 0
    
    async with Session() as session:
        for filepath in matrix_files:
            log.info(f"--- Обработка файла: {os.path.basename(filepath)} ---")
            matrix_df = load_kniga_3_matrix(filepath)
            
            if matrix_df is not None and not matrix_df.empty:
                async with session.begin():
                    log.info(f"Добавляю {len(matrix_df)} маршрутов (с пропуском дубликатов)...")
                    try:
                        # Используем "upsert" (ON CONFLICT DO NOTHING)
                        # Это медленнее, но гарантирует пропуск дубликатов
                        for record in matrix_df.to_dict(orient='records'):
                            stmt = pg_insert(TariffMatrix).values(**record).on_conflict_do_nothing(
                                index_elements=['station_a', 'station_b']
                            )
                            await session.execute(stmt)
                        
                        total_routes_added += len(matrix_df) # Считаем, сколько ПОПЫТАЛИСЬ добавить
                        
                    except Exception as e:
                        log.error(f"Неожиданная ошибка при вставке {os.path.basename(filepath)}: {e}", exc_info=True)
                        await session.rollback()
                await session.commit()
            else:
                log.warning(f"Файл {os.path.basename(filepath)} пропущен (пустой или ошибка загрузки).")

    log.info(f"✅ Миграция ВСЕХ матриц завершена. Попыток добавления: {total_routes_added}")
    # --- 🏁 КОНЕЦ ИЗМЕНЕНИЯ 🏁 ---

    log.info("🎉🎉🎉 == МИГРАЦИЯ ТАРИФНОЙ БАЗЫ УСПЕШНО ЗАВЕРШЕНА! ==")
    log.info("Папку zdtarif_bot/data можно удалять.")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_migrate())