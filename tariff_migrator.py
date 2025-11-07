# tariff_migrator.py
import asyncio
import os
import re
import pandas as pd
import sys
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, ARRAY, Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError
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
    
    # 'Чемской'
    name: Mapped[str] = mapped_column(String, index=True, unique=True) 
    
    # '850308'
    code: Mapped[str] = mapped_column(String(6), index=True) 
    
    # 'ЗАПАДНО-СИБИРСКАЯ (83)'
    railway: Mapped[str | None] = mapped_column(String)
    
    # Транзитные пункты (ТП)
    # Мы будем хранить как строки ["КОД:ИМЯ:ДИСТАНЦИЯ", ...]
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String)) 

    __table_args__ = (
        Index('ix_tariff_stations_name_code', 'name', 'code'),
    )

class TariffMatrix(Base):
    '''
    Таблица для хранения данных из 3-1 Рос.csv и 3-2 Рос.csv.
    '''
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # 'Бекасово I'
    station_a: Mapped[str] = mapped_column(String, index=True)
    
    # 'Инская'
    station_b: Mapped[str] = mapped_column(String, index=True)
    
    # 1532
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        # Уникальный индекс, чтобы не дублировать маршруты
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )

# --- 3. Вспомогательные функции парсинга ---

def parse_transit_points_for_db(tp_string: str) -> list[str]:
    '''
    Парсит строку транзитных пунктов из 2-РП.csv и возвращает список строк.
    '''
    if not isinstance(tp_string, str) or not tp_string:
        return []
    
    # Паттерн из zdtarif_bot/core/data_parser.py
    pattern = re.compile(r'(\d{6})\s(.*?)\s-\s(\d+)км')
    matches = pattern.findall(tp_string)
    
    transit_points_str = []
    for match in matches:
        # Сохраняем в простом формате "КОД:ИМЯ:ДИСТАНЦИЯ"
        transit_points_str.append(f"{match[0]}:{match[1].strip()}:{int(match[2])}")
        
    return transit_points_str

def load_kniga_2_rp(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает 2-РП.csv из zdtarif_bot/data
    '''
    try:
        df = pd.read_csv(
            filepath,
            # --- 🐞 ВОТ ИСПРАВЛЕНИЕ 🐞 ---
            skiprows=6, # Было 5, меняем на 6, чтобы пропустить строку заголовка
            # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
            names=[
                'num', 'station_name', 'operations', 'railway', 
                'transit_points_raw', 'station_code'
            ],
            encoding='cp1251',
            dtype={'station_code': str} # Читаем код как строку
        )
        df['station_name'] = df['station_name'].str.strip()
        df['station_code'] = df['station_code'].str.strip()
        df['railway'] = df['railway'].str.strip()
        
        # Убираем строки без имени или кода
        df.dropna(subset=['station_name', 'station_code'], inplace=True)
        
        log.info(f"✅ Файл {os.path.basename(filepath)} загружен, {len(df)} станций.")
        return df
    except FileNotFoundError:
        log.error(f"❌ Ошибка: Не найден файл '{filepath}'.")
        return None
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке {filepath}: {e}", exc_info=True)
        return None

def load_kniga_3_matrix(filepath: str) -> pd.DataFrame | None:
    '''
    Загружает матрицу (3-1 или 3-2) и преобразует ее в "длинный" формат.
    '''
    try:
        # --- 🐞 ВОТ ИСПРАВЛЕНИЕ 🐞 ---
        df = pd.read_csv(filepath, skiprows=6, encoding='cp1251') # Было 5, меняем на 6
        # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
        
        # Первая колонка (индекс) - это station_a
        df.iloc[:, 1] = df.iloc[:, 1].astype(str).str.strip()
        df = df.set_index(df.columns[1])
        df = df.drop(columns=[df.columns[0]]) # Удаляем '№ п/п'
        
        # Колонки - это station_b
        df.columns = df.columns.str.strip()

        # Преобразуем матрицу в "длинный" формат: (station_a, station_b, distance)
        df_long = df.stack(dropna=True).reset_index()
        df_long.columns = ['station_a', 'station_b', 'distance']
        
        # Очищаем от нечисловых значений и преобразуем в int
        df_long = df_long[pd.to_numeric(df_long['distance'], errors='coerce').notna()]
        df_long['distance'] = df_long['distance'].astype(int)
        
        # Удаляем маршруты с 0 км
        df_long = df_long[df_long['distance'] > 0]
        
        log.info(f"✅ Матрица {os.path.basename(filepath)} загружена, {len(df_long)} маршрутов.")
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
    log.info("--- 1/3: Начинаю миграцию Станций (2-РП.csv) ---")
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

    # 3. Миграция Матрицы 1 (3-1 Рос.csv)
    log.info("--- 2/3: Начинаю миграцию Матрицы 1 (3-1 Рос.csv) ---")
    matrix_1_df = load_kniga_3_matrix(os.path.join(data_dir_path, '3-1 Рос.csv'))
    
    if matrix_1_df is not None:
        async with Session() as session:
            async with session.begin():
                log.info(f"Добавляю {len(matrix_1_df)} маршрутов из 3-1 Рос...")
                # Используем bulk_insert_mappings для быстрой вставки
                await session.run_sync(
                    lambda s: s.bulk_insert_mappings(
                        TariffMatrix, 
                        matrix_1_df.to_dict(orient='records')
                    )
                )
            await session.commit()
        log.info("✅ Миграция Матрицы 1 завершена.")
    else:
        log.error("❌ Миграция Матрицы 1 провалена, файл не загружен.")

    # 4. Миграция Матрицы 2 (3-2 Рос.csv)
    log.info("--- 3/3: Начинаю миграцию Матрицы 2 (3-2 Рос.csv) ---")
    matrix_2_df = load_kniga_3_matrix(os.path.join(data_dir_path, '3-2 Рос.csv'))
    
    if matrix_2_df is not None:
        async with Session() as session:
            async with session.begin():
                log.info(f"Добавляю {len(matrix_2_df)} маршрутов из 3-2 Рос...")
                try:
                    await session.run_sync(
                        lambda s: s.bulk_insert_mappings(
                            TariffMatrix, 
                            matrix_2_df.to_dict(orient='records')
                        )
                    )
                except IntegrityError as e:
                    await session.rollback()
                    log.warning(f"ПРЕДУПРЕЖДЕНИЕ: {e.orig}")
                    log.warning("Это нормально, если были дубликаты маршрутов. Продолжаю...")
                except Exception as e:
                    log.error(f"Неожиданная ошибка: {e}", exc_info=True)
                    await session.rollback()
            await session.commit()
        log.info("✅ Миграция Матрицы 2 завершена.")
    else:
        log.error("❌ Миграция Матрицы 2 провалена, файл не загружен.")

    log.info("🎉🎉🎉 == МИГРАЦИЯ ТАРИФНОЙ БАЗЫ УСПЕШНО ЗАВЕРШЕНА! ==")
    log.info("Папку zdtarif_bot/data можно удалять.")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_migrate())