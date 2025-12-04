# tariff_migrator.py
print("🚀 ЗАПУСК СКРИПТА...")

import asyncio
import os
import re
import pandas as pd
import numpy as np
import sys
import glob
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert
import logging
from io import StringIO 

# --- 1. Настройка логгирования и .env ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Добавляем корень проекта в sys.path, чтобы найти zdtarif_bot/data
current_file_path = os.path.abspath(__file__)
project_root_dir = os.path.dirname(current_file_path)
sys.path.insert(0, project_root_dir)

# Загружаем переменные окружения
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
    name: Mapped[str] = mapped_column(String, index=True) 
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True) 
    railway: Mapped[str | None] = mapped_column(String)
    operations: Mapped[str | None] = mapped_column(String)
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
        # Пытаемся найти начало данных, пропуская шапку
        with open(filepath, 'r', encoding='cp1251') as f:
            lines = f.readlines()
        
        start_row = 0
        for i, line in enumerate(lines[:20]):
            if "Код станции" in line or "Наименование" in line:
                start_row = i + 1
                break
        
        if start_row == 0: start_row = 6

        df = pd.read_csv(
            filepath,
            skiprows=start_row,
            names=[
                'num', 'station_name', 'operations', 'railway', 
                'transit_points_raw', 'station_code'
            ],
            encoding='cp1251',
            dtype={'station_code': str},
            on_bad_lines='skip'
        )
        df['station_name'] = df['station_name'].str.strip()
        df['station_code'] = df['station_code'].str.strip()
        df['railway'] = df['railway'].str.strip()
        df['operations'] = df['operations'].str.strip()

        df.dropna(subset=['station_name', 'station_code'], inplace=True)
        
        # Удаляем дубликаты по КОДУ
        df.drop_duplicates(subset=['station_code'], keep='first', inplace=True)
        
        log.info(f"✅ Файл станций {os.path.basename(filepath)} загружен, {len(df)} записей.")
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
        with open(filepath, 'r', encoding='cp1251') as f:
            lines = f.readlines()

        # 1. Поиск границ заголовка и данных
        header_start_line = -1
        data_start_line = -1
        
        for i, line in enumerate(lines):
            if "Конечный пункт маршрута" in line and header_start_line == -1:
                header_start_line = i + 1 
            if "№ п/п" in line and "Начальный пункт" in line:
                data_start_line = i
                break
        
        if header_start_line == -1 or data_start_line == -1:
            log.error(f"⚠️ Не найдены маркеры начала в {filepath}.")
            return None

        # 2. Парсинг горизонтальных заголовков
        header_lines = lines[header_start_line:data_start_line]
        header_cols = {}
        
        for line in header_lines:
            cleaned_line = line.rstrip(',\n')
            cols = cleaned_line.split(',')
            for col_idx in range(2, len(cols)): 
                val = cols[col_idx].strip()
                if val:
                    if col_idx not in header_cols: header_cols[col_idx] = []
                    header_cols[col_idx].append(val)
        
        data_header_row = lines[data_start_line].strip().split(',')
        column_name_to_station_map = {}
        
        for col_idx, station_name_parts in header_cols.items():
            if col_idx < len(data_header_row):
                col_name_in_df = data_header_row[col_idx].strip()
                full_name = " ".join(station_name_parts)
                full_name = re.sub(r'\s+', ' ', full_name).strip()
                column_name_to_station_map[col_name_in_df] = full_name

        if not column_name_to_station_map:
             log.error(f"❌ Не удалось собрать карту заголовков для {filepath}.")
             return None
        
        log.info(f"Файл {os.path.basename(filepath)}: найдено {len(column_name_to_station_map)} целевых станций.")

        # 3. Чтение данных
        data_io = StringIO("".join(lines[data_start_line:]))
        df = pd.read_csv(data_io, header=0, encoding='cp1251', on_bad_lines='skip')
        
        df.rename(columns={df.columns[0]: 'num_pp', df.columns[1]: 'station_a'}, inplace=True)

        # 4. Склеивание разорванных названий станций отправления
        df = df.replace({np.nan: None})
        rows_to_drop = []
        
        for i in range(len(df)):
            if i == 0: continue
            curr_num = df.iloc[i]['num_pp']
            curr_name = str(df.iloc[i]['station_a'] or '').strip()
            
            if not curr_num and curr_name:
                prev_idx = i - 1
                while prev_idx in rows_to_drop and prev_idx >= 0:
                    prev_idx -= 1
                
                if prev_idx >= 0:
                    prev_name = str(df.iloc[prev_idx]['station_a']).strip()
                    df.iloc[prev_idx, 1] = f"{prev_name} {curr_name}".strip()
                    rows_to_drop.append(i)
            elif not curr_num and not curr_name:
                rows_to_drop.append(i)

        df.drop(df.index[rows_to_drop], inplace=True)
        
        # 5. Преобразование в длинный формат
        valid_value_vars = [c for c in df.columns if c in column_name_to_station_map]
        
        df_long = df.melt(
            id_vars=['station_a'], 
            value_vars=valid_value_vars, 
            var_name='station_b_key', 
            value_name='distance'
        )
        
        # 6. Очистка
        df_long = df_long[pd.to_numeric(df_long['distance'], errors='coerce').notna()]
        df_long['distance'] = df_long['distance'].astype(int)
        df_long = df_long[df_long['distance'] > 0]
        
        df_long['station_a'] = df_long['station_a'].astype(str).str.strip()
        df_long['station_b'] = df_long['station_b_key'].map(column_name_to_station_map)
        
        df_long.dropna(subset=['station_b', 'station_a'], inplace=True)
        
        final_df = df_long[['station_a', 'station_b', 'distance']].copy()
        
        log.info(f"✅ {os.path.basename(filepath)} обработан: {len(final_df)} маршрутов.")
        return final_df
        
    except Exception as e:
        log.error(f"❌ Критическая ошибка в {filepath}: {e}", exc_info=True)
        return None

# --- 4. Основная функция миграции ---

async def main_migrate():
    '''
    Главная функция. Подключается, пересоздает таблицы, загружает данные.
    '''
    if not TARIFF_DB_URL:
        log.error("❌ TARIFF_DATABASE_URL не найдена в .env файле. Миграция отменена.")
        return
        
    log.info(f"Подключение к новой базе данных тарифов...")
    
    # 1. Создаем движок и таблицы
    engine = create_async_engine(TARIFF_DB_URL)
    async with engine.begin() as conn:
        log.info("Очистка существующих таблиц (Drop All)...")
        await conn.run_sync(Base.metadata.drop_all)
        log.info("Создание новых таблиц (Create All)...")
        await conn.run_sync(Base.metadata.create_all)
    
    Session = async_sessionmaker(engine, expire_on_commit=False)
    
    # Ищем папку с данными
    data_dir_path = os.path.join(project_root_dir, 'zdtarif_bot', 'data')
    if not os.path.exists(data_dir_path):
        data_dir_path = os.path.join(project_root_dir, 'data')
        if not os.path.exists(data_dir_path):
             log.error(f"❌ Не могу найти папку 'data' или 'zdtarif_bot/data' в {project_root_dir}")
             await engine.dispose()
             return
    
    log.info(f"Использую папку с данными: {data_dir_path}")

    # --- 1. Миграция Станций ---
    log.info("--- 1/2: Начинаю миграцию Станций ---")
    
    station_files = glob.glob(os.path.join(data_dir_path, '2-РП*.csv'))
    all_stations_dfs = []
    for filepath in station_files:
        df = load_kniga_2_rp(filepath)
        if df is not None: all_stations_dfs.append(df)

    if all_stations_dfs:
        stations_df = pd.concat(all_stations_dfs, ignore_index=True)
        stations_df.drop_duplicates(subset=['station_code'], keep='first', inplace=True)
        
        total_stations = len(stations_df)
        log.info(f"Всего найдено {total_stations} УНИКАЛЬНЫХ станций.")
        
        stations_df = stations_df.where(pd.notnull(stations_df), None)

        async with Session() as session:
            # ✅ BATCH SIZE УМЕНЬШЕН ДО 1000
            batch_size = 1000 
            for start in range(0, total_stations, batch_size):
                end = min(start + batch_size, total_stations)
                batch = stations_df.iloc[start:end]
                
                values = []
                for _, row in batch.iterrows():
                    values.append({
                        'name': row['station_name'],
                        'code': row['station_code'],
                        'railway': row['railway'],
                        'operations': row['operations'],
                        'transit_points': parse_transit_points_for_db(row['transit_points_raw'])
                    })
                
                # Используем insert().on_conflict_do_nothing()
                stmt = pg_insert(TariffStation).values(values).on_conflict_do_nothing(
                    index_elements=['code']
                )
                await session.execute(stmt)
                await session.commit()
                log.info(f"Станции: обработано {end}/{total_stations}")
    else:
        log.warning("❌ Файлы станций не найдены!")

    # --- 2. Миграция Матриц ---
    log.info("--- 2/2: Начинаю миграцию Матриц ---")
    
    all_matrix_files = glob.glob(os.path.join(data_dir_path, '3-*.csv'))
    files_to_exclude = ['3-Вводные положения.csv', '3-Общие положения.csv']
    matrix_files_to_process = [f for f in all_matrix_files if os.path.basename(f) not in files_to_exclude]
    
    all_routes_dfs = []
    for filepath in matrix_files_to_process: 
        matrix_df = load_kniga_3_matrix(filepath)
        if matrix_df is not None and not matrix_df.empty:
            all_routes_dfs.append(matrix_df)

    if not all_routes_dfs:
        log.warning("⚠️ Не найдено маршрутов для вставки.")
    else:
        combined_routes_df = pd.concat(all_routes_dfs, ignore_index=True)
        # Симметрия
        log.info("Создание обратных маршрутов (симметрия)...")
        reversed_routes_df = combined_routes_df.rename(columns={'station_a': 'station_b', 'station_b': 'station_a'})
        final_routes_df = pd.concat([combined_routes_df, reversed_routes_df], ignore_index=True)
        
        # Удаляем дубликаты
        final_routes_df.drop_duplicates(subset=['station_a', 'station_b'], keep='first', inplace=True)

        total_routes_to_add = len(final_routes_df)
        log.info(f"Всего маршрутов для вставки: {total_routes_to_add}")
        
        async with Session() as session:
            # ✅ BATCH SIZE УМЕНЬШЕН ДО 1000
            BATCH_SIZE = 1000
            num_batches = (total_routes_to_add + BATCH_SIZE - 1) // BATCH_SIZE
            
            for i in range(num_batches):
                start_index = i * BATCH_SIZE
                end_index = min((i + 1) * BATCH_SIZE, total_routes_to_add)
                
                batch_df = final_routes_df.iloc[start_index:end_index]
                routes_to_insert = batch_df.to_dict(orient='records')
                
                try:
                    async with session.begin():
                        stmt = pg_insert(TariffMatrix).values(routes_to_insert).on_conflict_do_nothing(
                            index_elements=['station_a', 'station_b']
                        )
                        await session.execute(stmt)
                    
                    if (i + 1) % 50 == 0:
                        log.info(f"Матрица: загружено {end_index}/{total_routes_to_add}")
                        
                except Exception as e:
                    log.error(f"❌ Ошибка в пакете {i}: {e}", exc_info=True)

    log.info("🎉🎉🎉 == МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА! ==")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main_migrate())