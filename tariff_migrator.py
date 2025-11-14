# tariff_migrator.py
import asyncio
import os
import re
import pandas as pd
import numpy as np # Добавлен импорт numpy для работы с NaN/None
import sys
import glob
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError
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
        df['operations'] = df['operations'].str.strip()

        df.dropna(subset=['station_name', 'station_code'], inplace=True)
        
        # --- 🐞 ИСПРАВЛЕНИЕ: Удаляем дубликаты по КОДУ, а не по ИМЕНИ 🐞 ---
        df.drop_duplicates(subset=['station_code'], keep='first', inplace=True)
        # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
        
        log.info(f"✅ Файл {os.path.basename(filepath)} загружен, {len(df)} УНИКАЛЬНЫХ станций (по коду).")
        return df
    except FileNotFoundError:
        log.error(f"❌ Ошибка: Не найден файл '{filepath}'.")
        return None
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке {filepath}: {e}", exc_info=True)
        return None

def load_kniga_3_matrix(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает матрицу (3-*.csv) и преобразует ее в "длинный" формат,
    корректно считывая многострочные заголовки и объединяя многострочные названия станций.
    '''
    try:
        # 1. Читаем весь файл в строки
        with open(filepath, 'r', encoding='cp1251') as f:
            lines = f.readlines()

        # 2. Находим, где начинаются заголовки (station_b) и где основная таблица
        header_start_line = -1
        data_start_line = -1
        
        for i, line in enumerate(lines):
            # "Конечный пункт маршрута"
            if "Конечный пункт маршрута" in line and header_start_line == -1:
                header_start_line = i + 1 
            
            # "№ п/п"
            if "№ п/п" in line and "Начальный пункт маршрута" in line:
                data_start_line = i
                break
        
        if header_start_line == -1 or data_start_line == -1:
            log.error(f"❌ Не удалось найти 'Конечный пункт' или '№ п/п' в {filepath}.")
            return None

        # 3. Собираем карту заголовков (station_b)
        header_lines = lines[header_start_line:data_start_line]
        header_cols = {}
        
        for line in header_lines:
            cleaned_line = line.rstrip(',\n')
            cols = cleaned_line.split(',')
            
            for col_idx in range(2, len(cols)): 
                if col_idx not in header_cols:
                    header_cols[col_idx] = []
                
                cell_value = cols[col_idx].strip()
                if cell_value:
                    header_cols[col_idx].append(cell_value)
        
        header_map = {}
        col_count = 1
        for col_idx in sorted(header_cols.keys()):
            full_name = " ".join(header_cols[col_idx])
            full_name = re.sub(r'\s+', ' ', full_name).strip()
            if full_name:
                header_map[str(col_count)] = full_name
                col_count += 1
                
        if not header_map:
             log.error(f"❌ Не удалось собрать карту заголовков (station_b) из {filepath}.")
             return None
        
        log.info(f"Собрана карта из {len(header_map)} заголовков (station_b).")

        # 4. Читаем основную таблицу (начиная с "№ п/п")
        data_csv_lines = lines[data_start_line:]
        
        # Удаляем мусорные строки (продолжения заголовка)
        if len(data_csv_lines) > 3:
             # Индексы 1 и 2 в data_csv_lines (т.е. строки 643 и 644 в оригинале)
             del data_csv_lines[1:3] 
        
        data_io = StringIO("".join(data_csv_lines))

        df = pd.read_csv(
            data_io, 
            header=0, 
            encoding='cp1251'
        )

        # 5. Переименовываем первые две колонки
        df.rename(columns={
            df.columns[0]: 'num_pp',
            df.columns[1]: 'station_a'
        }, inplace=True)

        # --- НОВЫЙ ШАГ 5: Объединение строк с перенесенным названием станции ---
        
        log.info("Начинаю объединение многострочных названий станций...")
        
        # Заполняем все пустые ячейки (которые не NaN, а просто пустые строки) None
        df = df.replace({np.nan: None})
        
        rows_to_drop = []
        # Итерируем с конца, чтобы объединять "вверх"
        for i in range(len(df) - 1, 0, -1):
            # Проверяем, пуста ли колонка 'num_pp' (это признак переноса)
            if df.iloc[i]['num_pp'] is None:
                # Берем текущее название станции (перенос)
                current_station_part = str(df.iloc[i]['station_a']).strip()
                
                # Берем название станции из предыдущей строки (где должен быть номер)
                prev_station_name = str(df.iloc[i-1]['station_a']).strip()
                
                # Объединяем: полное имя + пробел + часть переноса
                new_station_name = f"{prev_station_name} {current_station_part}".strip()
                
                # Записываем объединенное название в строку с номером (i-1)
                df.iloc[i-1, df.columns.get_loc('station_a')] = new_station_name
                
                # Отмечаем строку переноса (i) для удаления
                rows_to_drop.append(i)

        # Удаляем строки переноса
        df.drop(df.index[rows_to_drop], inplace=True)
        log.info(f"Объединено и удалено {len(rows_to_drop)} строк-переносов.")
        
        # Очищаем колонку с номерами (для порядка, теперь она не нужна)
        df.dropna(subset=['station_a'], inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        # --- КОНЕЦ НОВОГО ШАГА 5 ---

        # 6. "Плавим" (melt) DataFrame
        col_station_b_numeric = [col for col in df.columns if col not in ['num_pp', 'station_a']]
        
        df_long = df.melt(
            id_vars=['station_a'], 
            value_vars=col_station_b_numeric, 
            var_name='station_b_num', 
            value_name='distance'
        )
        
        # 7. Очистка
        df_long['station_a'] = df_long['station_a'].astype(str).str.strip()
        df_long['station_b_num'] = df_long['station_b_num'].astype(str).str.strip()
        
        # 8. Очищаем от нечисловых значений и преобразуем в int
        df_long = df_long[pd.to_numeric(df_long['distance'], errors='coerce').notna()]
        df_long['distance'] = df_long['distance'].astype(int)
        
        # 9. Удаляем маршруты с 0 км
        df_long = df_long[df_long['distance'] > 0]
        
        # 10. *** ГЛАВНЫЙ ФИКС: Заменяем '1', '2' на имена ***
        df_long['station_b'] = df_long['station_b_num'].map(header_map)
        
        # 11. Проверяем, что все заменилось
        if df_long['station_b'].isnull().any():
            missing_keys = df_long[df_long['station_b'].isnull()]['station_b_num'].unique()
            log.warning(f"⚠️ В {filepath} не найдены имена для station_b ключей: {missing_keys[:10]}...")
            df_long.dropna(subset=['station_b'], inplace=True)

        # 12. Удаляем дубликаты и ненужный столбец
        df_long = df_long[['station_a', 'station_b', 'distance']]
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
    
    # Ищем папку с данными
    data_dir_path = os.path.join(project_root_dir, 'zdtarif_bot', 'data')
    if not os.path.exists(data_dir_path):
        data_dir_path = os.path.join(project_root_dir, 'data')
        if not os.path.exists(data_dir_path):
             log.error(f"❌ Не могу найти папку 'data' или 'zdtarif_bot/data' в {project_root_dir}")
             return
    
    log.info(f"Использую папку с данными: {data_dir_path}")

    # 2. Миграция станций (только 2-РП*.csv)
    log.info("--- 1/2: Начинаю миграцию Станций (только 2-РП*.csv) ---")
    
    station_files = glob.glob(os.path.join(data_dir_path, '2-РП*.csv'))
    log.info(f"Найдены файлы станций (2-РП): {[os.path.basename(f) for f in station_files]}")
    
    all_stations_dfs = []
    for filepath in station_files:
        df = load_kniga_2_rp(filepath)
        if df is not None:
            all_stations_dfs.append(df)

    if not all_stations_dfs:
        log.error("❌ Ни один файл станций (2-РП*.csv) не загружен. Миграция станций провалена.")
        return
        
    # Объединяем все DF и удаляем дубликаты
    stations_df = pd.concat(all_stations_dfs, ignore_index=True)
    stations_df.drop_duplicates(subset=['station_code'], keep='first', inplace=True)
    
    log.info(f"Всего найдено {len(stations_df)} УНИКАЛЬНЫХ станций во всех файлах.")
    
    stations_df = stations_df.where(pd.notnull(stations_df), None)

    async with Session() as session:
        async with session.begin():
            stations_to_add = []
            for _, row in stations_df.iterrows():
                stations_to_add.append(
                    TariffStation(
                        name=row['station_name'],
                        code=row['station_code'],
                        railway=row['railway'],
                        operations=row['operations'],
                        transit_points=parse_transit_points_for_db(row['transit_points_raw'])
                    )
                )
            log.info(f"Добавляю {len(stations_to_add)} станций в базу...")
            session.add_all(stations_to_add)
        await session.commit()
    log.info("✅ Миграция станций завершена.")


    # --- 3. Миграция (ВСЕ 3-*.csv, КРОМЕ "положений") ---
    log.info("--- 2/2: Начинаю миграцию Матриц (все 3-*.csv) ---")
    
    # 1. Находим АБСОЛЮТНО ВСЕ файлы 3-*.csv
    all_matrix_files = glob.glob(os.path.join(data_dir_path, '3-*.csv'))
    
    # 2. 🐞 НОВЫЙ ФИЛЬТР: Исключаем файлы, которые ТОЧНО не являются матрицами
    files_to_exclude = [
        '3-Вводные положения.csv',
        '3-Общие положения.csv'
    ]
    
    # Создаем итоговый список для обработки
    matrix_files_to_process = []
    for f_path in all_matrix_files:
        f_name = os.path.basename(f_path)
        if f_name not in files_to_exclude:
            matrix_files_to_process.append(f_path)
        else:
            log.warning(f"Файл {f_name} исключен из обработки, т.к. не является матрицей.")
            
    log.info(f"Найдены файлы матриц для обработки: {[os.path.basename(f) for f in matrix_files_to_process]}")


    total_routes_added = 0
    
    async with Session() as session:
        # 3. 🐞 Используем отфильтрованный список
        for filepath in matrix_files_to_process: 
                
            log.info(f"--- Обработка файла: {os.path.basename(filepath)} ---")
            matrix_df = load_kniga_3_matrix(filepath)
            
            if matrix_df is not None and not matrix_df.empty:
                async with session.begin():
                    log.info(f"Добавляю {len(matrix_df)} маршрутов (с пропуском дубликатов (ON CONFLICT DO NOTHING))...")
                    try:
                        # Используем "upsert" (ON CONFLICT DO NOTHING)
                        for record in matrix_df.to_dict(orient='records'):
                            stmt = pg_insert(TariffMatrix).values(**record).on_conflict_do_nothing(
                                index_elements=['station_a', 'station_b']
                            )
                            await session.execute(stmt)
                        
                        total_routes_added += len(matrix_df) 
                        
                    except Exception as e:
                        log.error(f"Неожиданная ошибка при вставке {os.path.basename(filepath)}: {e}", exc_info=True)
                        await session.rollback()
                await session.commit()
            else:
                log.warning(f"Файл {os.path.basename(filepath)} пропущен (пустой или ошибка загрузки).")

    log.info(f"✅ Миграция матриц завершена. Всего попыток добавления маршрутов: {total_routes_added}")

    log.info("🎉🎉🎉 == МИГРАЦИЯ ТАРИФНОЙ БАЗЫ УСПЕШНО ЗАВЕРШЕНА! ==")
    
    await engine.dispose()


if __name__ == "__main__":
    env_path = os.path.join(project_root_dir, '.env')
    if os.path.exists(env_path):
        log.info(f"Загружаю .env из {env_path}")
        load_dotenv(dotenv_path=env_path)
    else:
        log.warning(f"Файл .env не найден в {project_root_dir}, использую переменные окружения системы.")
        
    TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")
    
    asyncio.run(main_migrate())