# services/dislocation_importer.py

import pandas as pd
import asyncio
import re
from typing import Optional, Dict
from sqlalchemy.future import select

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ (на основе 'tree') ---
# Файлы 'db.py', 'models.py' и 'logger.py' находятся в корне проекта.
from db import async_session_maker
from models import Tracking, TrainEventLog
from logger import logger
from datetime import datetime
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---


# =========================================================================
# === 1. КАРТА СОПОСТАВЛЕНИЯ ДЛЯ НОВОГО ФОРМАТА ===
# =========================================================================

# --- НОВЫЙ МЭППИНГ РЖД (45 полей) ---
COLUMN_MAPPING_RZD_NEW = {
    'Номер контейнера': 'container_number',
    'Номер накладной': 'waybill',
    'Тип контейнера': 'container_type',
    'Дата и время начала рейса': 'trip_start_datetime',
    'Государство отправления': 'from_state',
    'Станция отправления': 'from_station',
    'Дорога отправления': 'from_road',
    'Дата и время окончания рейса': 'trip_end_datetime',
    'Страна назначения': 'to_country',
    'Дорога назначения': 'to_road',
    'Станция назначения': 'to_station',
    'Грузоотправитель (ТГНЛ)': 'sender_tgnl',
    'Грузоотправитель': 'sender_name_short',
    'Грузоотправитель (ОКПО)': 'sender_okpo',
    'Грузоотправитель (наим)': 'sender_name',
    'Грузополучатель (ТГНЛ)': 'receiver_tgnl',
    'Грузополучатель': 'receiver_name_short',
    'Грузополучатель (ОКПО)': 'receiver_okpo',
    'Грузополучатель (наим)': 'receiver_name',
    'Наименование груза': 'cargo_name',
    'Код груза ГНГ': 'cargo_gng_code',
    'Вес груза (кг)': 'cargo_weight_kg',
    'Станция операции': 'current_station',
    'Операция': 'operation',
    'Дорога операции': 'operation_road',
    'Мнемокод операции': 'operation_mnemonic',
    'Дата и время операции': 'operation_date',
    'Состояние контейнера': 'container_state',
    'Индекс поезда с наименованиями станций': 'train_index_full',
    'Номер поезда': 'train_number',
    'Номер вагона': 'wagon_number',
    'Количество пломб': 'seals_count',
    'Государство приема': 'accept_state',
    'Государство сдачи': 'surrender_state',
    'Дорога приема': 'accept_road',
    'Дорога сдачи': 'surrender_road',
    'Нормативный срок доставки': 'delivery_deadline',
    'Расстояние общее': 'total_distance',
    'Расстояние пройденное': 'distance_traveled',
    'Расстояние оставшееся': 'km_left',
    'Время простоя под последней операцией (сутки:часы:минуты)': 'last_op_idle_time_str',
    'Время простоя под последней операцией (сутки)': 'last_op_idle_days',
    'Идентификатор отправки': 'dispatch_id',
    'Идентификатор накладной': 'waybill_id',
    'Признак груж. рейса': 'is_loaded_trip',
}

# =========================================================================
# === 2. ХЕЛПЕР ЗАПОЛНЕНИЯ ===
# =========================================================================

def _fill_empty_rows_with_previous(df: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """Заполняет пустые значения в указанном столбце предыдущими значениями."""
    df[column_name] = df[column_name].ffill()
    return df

# =========================================================================
# === 3. ЧИТАТЕЛЬ ФАЙЛОВ (ТОЛЬКО НОВЫЙ ФОРМАТ) ===
# =========================================================================

def _read_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """
    Читатель Excel. Распознает НОВЫЙ формат РЖД (skiprows=3).
    Возвращает DataFrame с УЖЕ ПЕРЕИМЕНОВАННЫМИ столбцами (ключами модели).
    """
    logger.info(f"Чтение файла дислокации (ожидается НОВЫЙ формат): {filepath}")
    
    try:
        df = pd.read_excel(filepath, skiprows=3, header=0, engine='openpyxl')
        
        # Маркер-столбец: 'Идентификатор отправки'
        if 'Идентификатор отправки' not in df.columns and 'Тип контейнера' not in df.columns:
            logger.error(f"Файл {filepath} не похож на НОВЫЙ формат (РЖД, 45 столбцов). Пропускаем.")
            return None

        logger.info(f"Обнаружен НОВЫЙ формат дислокации (РЖД, 45 столбцов).")
        
        # 1. Отбираем только нужные столбцы
        valid_columns = [col for col in df.columns if col in COLUMN_MAPPING_RZD_NEW]
        if not valid_columns:
            logger.error("Новый формат распознан, но не найдено столбцов из COLUMN_MAPPING_RZD_NEW.")
            return None
        df = df[valid_columns]
        
        # 2. Переименовываем в ключи модели
        df.rename(columns=COLUMN_MAPPING_RZD_NEW, inplace=True)
        
        # 3. Заполняем пропуски в номерах
        if 'container_number' in df.columns:
            df = _fill_empty_rows_with_previous(df, 'container_number')
        else:
            logger.error("Критическая ошибка: 'Номер контейнера' не найден в НОВОМ файле.")
            return None

        # 4. Заменяем NaN/NaT на None
        df = df.where(pd.notna(df), None)
        return df
            
    except Exception as e:
        logger.error(f"Ошибка при чтении файла {filepath} как нового формата: {e}", exc_info=True)
        return None

# =========================================================================
# === 4. УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ДЛЯ БД ===
# =========================================================================
# (Этот код почти не меняется, он работает с УЖЕ ОБРАБОТАННЫМ DataFrame)

async def process_dislocation_file(filepath: str):
    """
    Обрабатывает файл дислокации, обновляет/вставляет данные в БД
    и готовит события для логгирования.
    Работает с УЖЕ подготовленным DataFrame из _read_excel_data.
    """
    
    # 1. _read_excel_data ТЕПЕРЬ возвращает df с ПЕРЕИМЕНОВАННЫМИ столбцами
    df = await asyncio.to_thread(_read_excel_data, filepath)
    if df is None:
        logger.warning(f"Файл {filepath} не был обработан, dataframe пуст или не распознан формат.")
        return 0

    # 2. Преобразуем dataframe в список словарей
    data_rows = df.to_dict('records') 
    
    updated_count = 0
    inserted_count = 0
    events_to_log = [] 

    async with async_session_maker() as session:
        
        # 3. Собираем номера контейнеров и предзагружаем их из БД
        container_numbers_from_file = [
            row['container_number'] for row in data_rows if row.get('container_number')
        ]
        if not container_numbers_from_file:
            logger.warning(f"В файле {filepath} не найдено ни одной строки с номером контейнера.")
            return 0
            
        existing_trackings = (await session.execute(
            select(Tracking).where(Tracking.container_number.in_(set(container_numbers_from_file)))
        )).scalars().all()
        tracking_map = {t.container_number: t for t in existing_trackings}

        # 4. Итерируем по ГОТОВЫМ словарям
        for row_data in data_rows:
            
            container_number = row_data.get('container_number')
            if not container_number:
                continue

            # --- (Опционально) Приведение типов ---
            
            if 'is_loaded_trip' in row_data and row_data['is_loaded_trip'] is not None:
                # Pandas может прочитать "1" как 1 (число) или "1" (строка)
                try:
                    row_data['is_loaded_trip'] = bool(int(row_data['is_loaded_trip']))
                except (ValueError, TypeError):
                    row_data['is_loaded_trip'] = None # или False

            # (Пример для чисел)
            for key in ['cargo_weight_kg', 'total_distance', 'distance_traveled', 'km_left']:
                if key in row_data and row_data[key] is not None:
                    try:
                        # Убираем пробелы (если ' 9529 ' -> 9529)
                        cleaned_val = str(row_data[key]).strip()
                        row_data[key] = int(float(cleaned_val))
                    except (ValueError, TypeError):
                        row_data[key] = None 
            # --- (Конец приведения типов) ---

            existing_entry = tracking_map.get(container_number)
            
            # `operation_date` уже должна быть datetime объектом из pandas
            new_operation_date = row_data.get('operation_date') 
            
            # Проверяем, что это действительно datetime, а не NaT (Not-a-Time)
            if pd.isna(new_operation_date):
                new_operation_date = None
            
            if existing_entry:
                # --- ЛОГИКА ОБНОВЛЕНИЯ (взята из вашего repomix) ---
                current_date = existing_entry.operation_date 
                
                # (Мы уже изменили тип в БД на DateTime, парсинг не нужен)

                if new_operation_date and (current_date is None or new_operation_date > current_date):
                    # Обновляем все поля из row_data
                    # (Он обновит только те поля, что есть в row_data)
                    for key, value in row_data.items():
                        setattr(existing_entry, key, value)
                    
                    events_to_log.append(TrainEventLog(
                        container_number=container_number,
                        event_name=row_data.get('operation', 'Обновление'),
                        event_description=f"Станция: {row_data.get('current_station')}, Вагон: {row_data.get('wagon_number')}"
                    ))
                    updated_count += 1
            else:
                # --- ЛОГИКА СОЗДАНИЯ (взята из вашего repomix) ---
                # **row_data передаст все 45 полей, которые есть
                new_entry = Tracking(**row_data) 
                session.add(new_entry)
                tracking_map[container_number] = new_entry 
                
                events_to_log.append(TrainEventLog(
                    container_number=container_number,
                    event_name="Запись создана",
                    event_description=f"Контейнер добавлен в слежение. Станция: {row_data.get('current_station')}"
                ))
                inserted_count += 1
                
        try:
            if events_to_log:
                # (Убедитесь, что ваша модель TrainEventLog имеет метод bulk_create)
                # Если нет, используйте session.add_all(events_to_log)
                session.add_all(events_to_log)
            
            await session.commit()
            logger.info(f"Успешно сохранено в БД: {inserted_count} новых, {updated_count} обновленных.")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при сохранении в БД: {e}", exc_info=True)
            return 0

    logger.info(f"[Dislocation Import] Обработка {filepath} завершена.")
    return inserted_count + updated_count