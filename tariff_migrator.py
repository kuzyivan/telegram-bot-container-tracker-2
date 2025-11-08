# tariff_migrator.py
import asyncio
import os
import re
import pandas as pd
import sys
import glob
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
import logging
from io import StringIO # 🐞 Добавлено для чтения строк как файла

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
    
    # --- 🐞 ИСПРАВЛЕНИЕ: name НЕ уникально ---
    name: Mapped[str] = mapped_column(String, index=True) 
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
    
    # --- 🐞 ИСПРАВЛЕНИЕ: code УНИКАЛЕН ---
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True) 
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

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

# --- 🐞 НАЧАЛО ИСПРАВЛЕННОЙ ФУНКЦИИ 🐞 ---
def load_kniga_3_matrix(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает матрицу (3-*.csv) и преобразует ее в "длинный" формат,
    корректно считывая многострочные заголовки.
    '''
    try:
        # 1. Читаем весь файл в строки
        with open(filepath, 'r', encoding='cp1251') as f:
            lines = f.readlines()

        # 2. Находим, где начинаются заголовки (station_b) и где основная таблица
        header_start_line = -1
        data_start_line = -1
        
        for i, line in enumerate(lines):
            # "Конечный пункт маршрута" (Source 13)
            if "Конечный пункт маршрута" in line and header_start_line == -1:
                header_start_line = i + 1 # Начинаем со следующей строки (Source 15)
            
            # "№ п/п" (Source 642)
            if "№ п/п" in line and "Начальный пункт маршрута" in line:
                data_start_line = i
                break
        
        if header_start_line == -1 or data_start_line == -1:
            log.error(f"❌ Не удалось найти 'Конечный пункт' или '№ п/п' в {filepath}.")
            return None

        # 3. Собираем карту заголовков (station_b)
        # Они в строках с header_start_line по data_start_line - 1
        # Формат: ,,ИМЯ 1 (код), ИМЯ 2 (код), ...
        #         ,,(код), (код), ...
        #         ,,до),,), ...
        # Эти строки нужно "склеить" по столбцам.
        
        header_lines = lines[header_start_line:data_start_line]
        
        # header_cols[2] = ["Авдеевка (89", "89-я", "до)"]
        # header_cols[3] = ["Агрыз (24", "Горьк)"]
        header_cols = {}
        
        for line in header_lines:
            # Убираем лишние запятые в конце, если есть
            cleaned_line = line.rstrip(',\n')
            cols = cleaned_line.split(',')
            
            # Итерируемся по индексам столбцов, начиная с 3-го (индекс 2)
            for col_idx in range(2, len(cols)): 
                if col_idx not in header_cols:
                    header_cols[col_idx] = []
                
                cell_value = cols[col_idx].strip()
                if cell_value:
                    header_cols[col_idx].append(cell_value)
        
        # Теперь объединяем ячейки в полные имена и нумеруем их
        # header_map = {'1': 'Имя 1', '2': 'Имя 2', ...}
        header_map = {}
        col_count = 1
        # Сортируем по индексу столбца (col_idx), чтобы сохранить порядок
        for col_idx in sorted(header_cols.keys()):
            full_name = " ".join(header_cols[col_idx])
            # Очищаем от лишних пробелов
            full_name = re.sub(r'\s+', ' ', full_name).strip()
            if full_name:
                # Ключ - это *номер столбца*, как в строке [Source 642]
                header_map[str(col_count)] = full_name
                col_count += 1
                
        if not header_map:
             log.error(f"❌ Не удалось собрать карту заголовков (station_b) из {filepath}.")
             return None
        
        log.info(f"Собрана карта из {len(header_map)} заголовков (station_b).")

        # 4. Читаем основную таблицу (начиная с "№ п/п")
        # Мы используем StringIO, чтобы передать pandas только нужные строки
        data_csv_lines = lines[data_start_line:]
        
        # В файлах 3-1/3-2.csv строки 643 и 644 (индексы 1 и 2 в data_csv_lines) 
        # являются мусорными продолжениями заголовка. Удаляем их.
        if len(data_csv_lines) > 3:
             del data_csv_lines[1:3] 
        
        data_io = StringIO("".join(data_csv_lines))

        df = pd.read_csv(
            data_io, 
            header=0, # <-- "№ п/п"
            encoding='cp1251'
        )

        # 5. Переименовываем первые две колонки
        df.rename(columns={
            df.columns[0]: 'num_pp',
            df.columns[1]: 'station_a'
        }, inplace=True)

        # 6. "Плавим" (melt) DataFrame
        # Колонки station_b - это все, КРОМЕ 'num_pp' и 'station_a'
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
# --- 🐞 КОНЕЦ ИСПРАВЛЕННОЙ ФУНКЦИИ 🐞 ---


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
    
    # 🐞 ПРЕДПОЛОЖЕНИЕ: Файлы лежат в 'zdtarif_bot/data'
    # Если скрипт лежит в другом месте, измените этот путь
    data_dir_path = os.path.join(project_root_dir, 'zdtarif_bot', 'data')
    
    # Если папки 'zdtarif_bot/data' нет, ищем 'data'
    if not os.path.exists(data_dir_path):
        data_dir_path = os.path.join(project_root_dir, 'data')
        if not os.path.exists(data_dir_path):
             log.error(f"❌ Не могу найти папку 'data' или 'zdtarif_bot/data' в {project_root_dir}")
             return
    
    log.info(f"Использую папку с данными: {data_dir_path}")
    
    stations_df = load_kniga_2_rp(os.path.join(data_dir_path, '2-РП.csv'))
    
    if stations_df is not None:
        
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
    else:
        log.error("❌ Миграция станций провалена, файл 2-РП.csv не загружен.")
        return

    # 3. Миграция (ТОЛЬКО 3-1 и 3-2 Рос)
    log.info("--- 2/2: Начинаю миграцию Матриц (3-1 Рос, 3-2 Рос) ---")
    
    matrix_files = [
        os.path.join(data_dir_path, '3-1 Рос.csv'),
        os.path.join(data_dir_path, '3-2 Рос.csv')
    ]

    total_routes_added = 0
    
    async with Session() as session:
        for filepath in matrix_files:
            if not os.path.exists(filepath):
                log.error(f"❌ Файл матрицы {filepath} не найден. Пропуск.")
                continue
                
            log.info(f"--- Обработка файла: {os.path.basename(filepath)} ---")
            matrix_df = load_kniga_3_matrix(filepath)
            
            if matrix_df is not None and not matrix_df.empty:
                async with session.begin():
                    log.info(f"Добавляю {len(matrix_df)} маршрутов (с пропуском дубликатов)...")
                    try:
                        # Используем "upsert" (ON CONFLICT DO NOTHING)
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

    log.info(f"✅ Миграция матриц завершена. Попыток добавления: {total_routes_added}")

    log.info("🎉🎉🎉 == МИГРАЦИЯ ТАРИФНОЙ БАЗЫ УСПЕШНО ЗАВЕРШЕНА! ==")
    
    await engine.dispose()


if __name__ == "__main__":
    # 🐞 Добавляем проверку пути к .env
    env_path = os.path.join(project_root_dir, '.env')
    if os.path.exists(env_path):
        log.info(f"Загружаю .env из {env_path}")
        load_dotenv(dotenv_path=env_path)
    else:
        log.warning(f"Файл .env не найден в {project_root_dir}, использую переменные окружения системы.")
        
    TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")
    
    asyncio.run(main_migrate())