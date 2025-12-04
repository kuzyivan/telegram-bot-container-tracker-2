# tariff_migrator.py
import asyncio
import os
import re
import pandas as pd
import numpy as np
import sys
import glob
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert
import logging
from io import StringIO 

# --- 1. Настройка логгирования и .env ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Добавляем корень проекта в sys.path
current_file_path = os.path.abspath(__file__)
project_root_dir = os.path.dirname(current_file_path)
sys.path.insert(0, project_root_dir)

load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

# --- 2. Определение ORM Моделей ---

class Base(DeclarativeBase):
    pass

class TariffStation(Base):
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
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )

# --- 3. Вспомогательные функции ---

def parse_transit_points_for_db(tp_string: str) -> list[str]:
    if not isinstance(tp_string, str) or not tp_string:
        return []
    pattern = re.compile(r'(\d{6})\s(.*?)\s-\s(\d+)км')
    matches = pattern.findall(tp_string)
    transit_points_str = []
    for match in matches:
        transit_points_str.append(f"{match[0]}:{match[1].strip()}:{int(match[2])}")
    return transit_points_str

def load_kniga_2_rp(filepath: str) -> pd.DataFrame | None:
    try:
        # Пытаемся найти начало данных, пропуская шапку
        # Обычно шапка занимает 5-7 строк, ищем строку где есть цифры в первой колонке
        with open(filepath, 'r', encoding='cp1251') as f:
            lines = f.readlines()
        
        start_row = 0
        for i, line in enumerate(lines[:20]):
            if "Код станции" in line or "Наименование" in line:
                start_row = i + 1
                break
        
        # Если не нашли заголовки, берем хардкод 6
        if start_row == 0: start_row = 6

        df = pd.read_csv(
            filepath,
            skiprows=start_row,
            names=['num', 'station_name', 'operations', 'railway', 'transit_points_raw', 'station_code'],
            encoding='cp1251',
            dtype={'station_code': str},
            on_bad_lines='skip' # Пропускаем битые строки
        )
        df['station_name'] = df['station_name'].str.strip()
        df['station_code'] = df['station_code'].str.strip()
        
        df.dropna(subset=['station_name', 'station_code'], inplace=True)
        df.drop_duplicates(subset=['station_code'], keep='first', inplace=True)
        
        log.info(f"✅ Файл станций {os.path.basename(filepath)}: загружено {len(df)} записей.")
        return df
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке станций {filepath}: {e}", exc_info=True)
        return None

def load_kniga_3_matrix(filepath: str) -> pd.DataFrame | None:
    '''
    Улучшенная функция загрузки матрицы.
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
            # Ищем строку, где начинаются данные. Обычно она содержит "№ п/п"
            if "№ п/п" in line and "Начальный пункт" in line:
                data_start_line = i
                break
        
        if header_start_line == -1 or data_start_line == -1:
            log.error(f"⚠️ Странный формат файла {filepath}. Не найдены маркеры начала.")
            return None

        # 2. Парсинг названий станций назначения (Горизонтальный заголовок)
        # Они разбросаны вертикально над основной таблицей
        header_lines = lines[header_start_line:data_start_line]
        header_cols = {}
        
        for line in header_lines:
            cleaned_line = line.rstrip(',\n')
            cols = cleaned_line.split(',')
            # Первые 2 колонки - это описание строк, пропускаем
            for col_idx in range(2, len(cols)): 
                val = cols[col_idx].strip()
                if val:
                    if col_idx not in header_cols: header_cols[col_idx] = []
                    header_cols[col_idx].append(val)
        
        # Собираем карту { "Номер колонки в CSV": "Полное имя станции" }
        # Важно: Pandas read_csv при чтении DATA SECTION даст колонкам имена '1', '2', '3' и т.д.
        # Нам нужно сопоставить порядковый номер колонки данных с именем.
        
        # Находим первую колонку с данными в строке заголовка данных
        # Строка data_start_line выглядит как: "№ п/п,Нач.пункт,1,2,3,4..."
        data_header_row = lines[data_start_line].strip().split(',')
        
        # Карта: ключ - имя колонки в DataFrame ('1', '2'...), значение - Имя станции
        column_name_to_station_map = {}
        
        # Индексы в data_header_row сдвинуты относительно header_cols на то же значение
        for col_idx, station_name_parts in header_cols.items():
            if col_idx < len(data_header_row):
                col_name_in_df = data_header_row[col_idx].strip() # Это будет '1', '2', '5' и т.д.
                full_name = " ".join(station_name_parts)
                full_name = re.sub(r'\s+', ' ', full_name).strip()
                column_name_to_station_map[col_name_in_df] = full_name

        if not column_name_to_station_map:
             log.error(f"❌ Не удалось собрать карту заголовков для {filepath}.")
             return None
        
        log.info(f"Файл {os.path.basename(filepath)}: найдено {len(column_name_to_station_map)} целевых станций.")

        # 3. Чтение данных
        # Считываем всё, начиная со строки заголовка данных
        data_io = StringIO("".join(lines[data_start_line:]))
        
        df = pd.read_csv(data_io, header=0, encoding='cp1251', on_bad_lines='skip')
        
        # Переименуем первые колонки для удобства
        df.rename(columns={df.columns[0]: 'num_pp', df.columns[1]: 'station_a'}, inplace=True)

        # 4. "Склеивание" разорванных названий станций отправления (вертикальных)
        # Если num_pp пустой, значит это продолжение названия предыдущей станции
        df = df.replace({np.nan: None})
        rows_to_drop = []
        
        for i in range(len(df)):
            # Если это первая строка, пропускаем
            if i == 0: continue
            
            curr_num = df.iloc[i]['num_pp']
            curr_name = str(df.iloc[i]['station_a'] or '').strip()
            
            # Если нет номера, но есть текст в station_a - это продолжение предыдущей
            if not curr_num and curr_name:
                prev_idx = i - 1
                # Ищем "родителя" выше
                while prev_idx in rows_to_drop and prev_idx >= 0:
                    prev_idx -= 1
                
                if prev_idx >= 0:
                    prev_name = str(df.iloc[prev_idx]['station_a']).strip()
                    df.iloc[prev_idx, 1] = f"{prev_name} {curr_name}".strip()
                    rows_to_drop.append(i)
            # Если и номера нет, и имени нет - мусор
            elif not curr_num and not curr_name:
                rows_to_drop.append(i)

        df.drop(df.index[rows_to_drop], inplace=True)
        
        # 5. Преобразование в длинный формат (Melt)
        # Оставляем только те колонки, которые есть в нашей карте станций
        valid_value_vars = [c for c in df.columns if c in column_name_to_station_map]
        
        df_long = df.melt(
            id_vars=['station_a'], 
            value_vars=valid_value_vars, 
            var_name='station_b_key', 
            value_name='distance'
        )
        
        # 6. Очистка и маппинг
        df_long = df_long[pd.to_numeric(df_long['distance'], errors='coerce').notna()]
        df_long['distance'] = df_long['distance'].astype(int)
        df_long = df_long[df_long['distance'] > 0]
        
        df_long['station_a'] = df_long['station_a'].astype(str).str.strip()
        # Мапим код колонки ('1', '2') на реальное имя ('Москва...')
        df_long['station_b'] = df_long['station_b_key'].map(column_name_to_station_map)
        
        df_long.dropna(subset=['station_b', 'station_a'], inplace=True)
        
        # Убираем лишнее
        final_df = df_long[['station_a', 'station_b', 'distance']].copy()
        
        log.info(f"✅ {os.path.basename(filepath)} обработан: {len(final_df)} маршрутов.")
        return final_df
        
    except Exception as e:
        log.error(f"❌ Критическая ошибка в {filepath}: {e}", exc_info=True)
        return None

# --- 4. Основная логика ---

async def main_migrate():
    if not TARIFF_DB_URL:
        log.error("❌ TARIFF_DATABASE_URL не задан.")
        return
        
    engine = create_async_engine(TARIFF_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all) # Создаем если нет (лучше дропнуть вручную если надо чистую)
        # Если нужна полная очистка перед загрузкой:
        log.info("Очистка таблиц перед загрузкой...")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    Session = async_sessionmaker(engine, expire_on_commit=False)
    
    # Путь к данным
    data_dir = os.path.join(project_root_dir, 'zdtarif_bot', 'data')
    if not os.path.exists(data_dir):
        data_dir = os.path.join(project_root_dir, 'data') # Fallback

    # 1. Станции
    log.info("--- Загрузка Станций ---")
    station_files = glob.glob(os.path.join(data_dir, '2-РП*.csv'))
    all_stations = []
    for f in station_files:
        df = load_kniga_2_rp(f)
        if df is not None: all_stations.append(df)
    
    if all_stations:
        full_stations = pd.concat(all_stations).drop_duplicates(subset=['station_code'])
        async with Session() as session:
            # Batch insert
            batch_size = 5000
            total = len(full_stations)
            for start in range(0, total, batch_size):
                end = min(start + batch_size, total)
                batch = full_stations.iloc[start:end]
                values = []
                for _, row in batch.iterrows():
                    values.append({
                        'name': row['station_name'],
                        'code': row['station_code'],
                        'railway': row['railway'],
                        'operations': row['operations'],
                        'transit_points': parse_transit_points_for_db(row['transit_points_raw'])
                    })
                await session.execute(pg_insert(TariffStation).values(values).on_conflict_do_nothing())
                await session.commit()
                log.info(f"Станции: обработано {end}/{total}")

    # 2. Матрицы
    log.info("--- Загрузка Матриц ---")
    matrix_files = glob.glob(os.path.join(data_dir, '3-*.csv'))
    # Исключаем не-матрицы
    matrix_files = [f for f in matrix_files if "Вводные" not in f and "Общие" not in f]
    
    combined_dfs = []
    for f in matrix_files:
        df = load_kniga_3_matrix(f)
        if df is not None: combined_dfs.append(df)
    
    if not combined_dfs:
        log.error("Нет данных матриц для загрузки.")
        return

    full_matrix = pd.concat(combined_dfs, ignore_index=True)
    
    # Создаем симметричные маршруты (B -> A)
    log.info("Генерация обратных маршрутов...")
    reversed_matrix = full_matrix.rename(columns={'station_a': 'station_b', 'station_b': 'station_a'})
    full_matrix = pd.concat([full_matrix, reversed_matrix], ignore_index=True)
    
    # Удаляем дубликаты
    full_matrix.drop_duplicates(subset=['station_a', 'station_b'], inplace=True)
    
    total_routes = len(full_matrix)
    log.info(f"Всего маршрутов для загрузки: {total_routes}")
    
    async with Session() as session:
        batch_size = 5000 # Безопасный размер
        for start in range(0, total_routes, batch_size):
            end = min(start + batch_size, total_routes)
            batch = full_matrix.iloc[start:end]
            records = batch.to_dict(orient='records')
            
            stmt = pg_insert(TariffMatrix).values(records).on_conflict_do_nothing(
                index_elements=['station_a', 'station_b']
            )
            await session.execute(stmt)
            await session.commit()
            if start % 50000 == 0:
                log.info(f"Матрица: загружено {end}/{total_routes}")

    log.info("🎉 Миграция успешно завершена!")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main_migrate())