# services/dislocation_importer.py

import pandas as pd
import asyncio
import re
import os  # <-- ПЕРЕМЕЩАЕМ ИМПОРТ OS ВВЕРХ
from typing import Optional, Dict
from sqlalchemy.future import select
from sqlalchemy import update, delete

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ (на основе 'tree') ---
# Файлы 'db.py', 'models.py' и 'logger.py' находятся в корне проекта.
from db import async_sessionmaker
from models import Tracking, TrainEventLog
# --- ИСПРАВЛЕНИЕ ЛОГГЕРА (используем стандартный) ---
import logging
logger = logging.getLogger(__name__)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---
from datetime import datetime
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

# --- ОПРЕДЕЛЯЕМ ПАПКУ ДЛЯ ЗАГРУЗОК ---
# handlers/admin/uploads.py ожидает найти эту переменную здесь.
DOWNLOAD_DIR = "downloads"
# Убедимся, что папка существует при старте
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# ---


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
# === 2. ХЕЛПЕРЫ ===
# =========================================================================

def _fill_empty_rows_with_previous(df: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """Заполняет пустые значения в указанном столбце предыдущими значениями."""
    df[column_name] = df[column_name].ffill()
    return df

# =========================================================================
# === 3. "УМНЫЙ" ЧИТАТЕЛЬ ФАЙЛОВ ===
# =========================================================================

def _read_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """
    Считывает данные из .xlsx файла дислокации от РЖД, 
    пропуская 3 строки и используя 4-ю как заголовок.
    Возвращает DataFrame с УЖЕ ПЕРЕИМЕНОВАННЫМИ столбцами (ключами модели).
    """
    logger.info(f"Чтение файла дислокации: {filepath}")
    
    # --- Попытка №1: Прочитать как НОВЫЙ формат РЖД (skiprows=3) ---
    try:
        df = pd.read_excel(filepath, skiprows=3, header=0, engine='openpyxl')
        
        # Маркер-столбец: 'Идентификатор отправки' есть только в новом файле
        if 'Идентификатор отправки' in df.columns or 'Тип контейнера' in df.columns:
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
            
        else:
            logger.error(f"Файл {filepath} не похож на новый формат (нет маркер-столбцов).")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при чтении Excel файла {filepath}: {e}", exc_info=True)
        return None


# =========================================================================
# === 4. УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ДЛЯ БД ===
# =========================================================================

async def process_dislocation_file(filepath: str):
    """
    Обрабатывает файл дислокации, обновляет/вставляет данные в БД
    и готовит события для логгирования.
    """
    
    # 1. Читаем Excel, получаем df с ПРАВИЛЬНЫМИ именами столбцов
    df = await asyncio.to_thread(_read_excel_data, filepath)
    if df is None:
        logger.warning(f"Файл {filepath} не был обработан, dataframe пуст или не распознан формат.")
        return 0

    # 2. Преобразуем dataframe в список словарей
    data_rows = df.to_dict('records') 
    
    updated_count = 0
    inserted_count = 0
    events_to_log = [] 

    # --- ИСПРАВЛЕНИЕ ОШИБКИ TypeError: 'async_sessionmaker' object has no attribute 'execute'
    # Pylance был неправ, скобки () НУЖНЫ, чтобы *создать* сессию.
    # Ваш 'async_sessionmaker' (из db.py) не поддерживает 'async with'.
    # Используем 'try/finally'
    
    # Создаем сессию, ВЫЗЫВАЯ фабрику
    session = async_sessionmaker()
    try:
        
        # 3. Собираем номера контейнеров и предзагружаем их из БД
        container_numbers_from_file = [
            row['container_number'] for row in data_rows if row.get('container_number')
        ]
        if not container_numbers_from_file:
            logger.warning(f"В файле {filepath} не найдено ни одной строки с номером контейнера.")
            # return 0 (не прерываем, чтобы сессия закрылась в 'finally')
        else:
            existing_trackings = (await session.execute(
                select(Tracking).where(Tracking.container_number.in_(set(container_numbers_from_file)))
            )).scalars().all()
            tracking_map = {t.container_number: t for t in existing_trackings}

            # 4. Итерируем по ГОТОВЫМ словарям
            for row_data in data_rows:
                
                container_number = row_data.get('container_number')
                if not container_number:
                    continue

                # --- (ВАЖНО) Приведение типов ---
                
                if 'is_loaded_trip' in row_data and row_data['is_loaded_trip'] is not None:
                    row_data['is_loaded_trip'] = bool(row_data['is_loaded_trip'])
                
                # Конвертируем все столбцы с датами (Pandas их уже распознал)
                # Это решает ошибку "expected datetime, got str"
                for date_col in ['operation_date', 'trip_start_datetime', 'trip_end_datetime', 'delivery_deadline']:
                    if date_col in row_data and row_data[date_col] is not None:
                        # pd.to_datetime может вернуть NaT (Not a Time), который SQLAlchemy не любит
                        # NaT == None -> False, поэтому pd.isna()
                        if pd.isna(row_data[date_col]):
                            row_data[date_col] = None
                        else:
                            # Преобразуем в стандартный datetime Питона
                            try:
                                row_data[date_col] = pd.to_datetime(row_data[date_col]).to_pydatetime()
                            except:
                                # Если pandas не смог, ставим None
                                row_data[date_col] = None


                # Конвертируем числа (на всякий случай)
                for key in ['cargo_weight_kg', 'total_distance', 'distance_traveled', 'km_left']:
                    if key in row_data and row_data[key] is not None:
                        try:
                            row_data[key] = int(row_data[key])
                        except (ValueError, TypeError):
                            row_data[key] = None 
                # --- (Конец приведения типов) ---

                existing_entry = tracking_map.get(container_number)
                new_operation_date = row_data.get('operation_date') 
                
                if existing_entry:
                    # --- ЛОГИКА ОБНОВЛЕНИЯ ---
                    current_date = existing_entry.operation_date 

                    if new_operation_date and (current_date is None or new_operation_date > current_date):
                        # Обновляем все поля из row_data
                        for key, value in row_data.items():
                            # --- ИСПРАВЛЕНИЕ Pylance (2) ---
                            # Явно приводим ключ к str
                            setattr(existing_entry, str(key), value)
                            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                        
                        events_to_log.append(TrainEventLog(
                            container_number=container_number,
                            # (Обновлено на основе models.py)
                            train_number=row_data.get('train_number', 'N/A'),
                            event_description=row_data.get('operation', 'Обновление'),
                            station=row_data.get('current_station', 'N/A'),
                            event_time=new_operation_date
                        ))
                        updated_count += 1
                else:
                    # --- ЛОГИКА СОЗДАНИЯ ---
                    
                    # --- ИСПРАВЛЕНИЕ Pylance (3) ---
                    # Pylance хочет, чтобы ключи **kwargs были str
                    new_entry_data = {str(k): v for k, v in row_data.items()}
                    new_entry = Tracking(**new_entry_data) 
                    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                    
                    session.add(new_entry)
                    tracking_map[container_number] = new_entry 
                    
                    events_to_log.append(TrainEventLog(
                        container_number=container_number,
                        # (Обновлено на основе models.py)
                        train_number=row_data.get('train_number', 'N/A'),
                        event_description="Запись создана",
                        station=row_data.get('current_station', 'N/A'),
                        event_time=new_operation_date if new_operation_date else datetime.now() # (На всякий случай)
                    ))
                    inserted_count += 1
                    
        # --- (Часть блока try/finally) ---
        if events_to_log:
            # Используем стандартный session.add_all
            session.add_all(events_to_log)
        
        await session.commit()
        logger.info(f"Успешно сохранено в БД: {inserted_count} новых, {updated_count} обновленных.")
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка при сохранении в БД: {e}", exc_info=True)
        return 0
    finally:
        await session.close()
    # --- КОНЕЦ ИСПРАВЛЕНИЯ TypeError ---

    logger.info(f"[Dislocation Import] Обработка {filepath} завершена.")
    return inserted_count + updated_count


# =========================================================================
# === 5. ФУНКЦИЯ, ВЫЗЫВАЕМАЯ ПЛАНИРОВЩИКОМ (из scheduler.py) ===
# =========================================================================

from telegram import Bot
# import os # <-- УДАЛЕНО, так как перенесено вверх

# Фильтры из вашего repomix
SUBJECT_FILTER_DISLOCATION = r'^Отчёт слежения TrackerBot №'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru'
FILENAME_PATTERN_DISLOCATION = r'\.xlsx$'

async def check_and_process_dislocation(bot_instance: Bot):
    """Проверяет почту, обрабатывает файлы и рассылает уведомления."""
    
    # --- ИСПРАВЛЕНИЕ ЦИКЛИЧЕСКОГО ИМПОРТА (ОШИБКА 1 И 3) ---
    # Импортируем сервисы ВНУТРИ функции, а не снаружи
    # И импортируем МОДУЛИ, а не функции из них
    from services import imap_service
    from services import notification_service
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    
    logger.info("Scheduler: Запуск проверки дислокации...")
    try:
        # --- ИСПРАВЛЕНИЕ ВЫЗОВА:
        # Вызываем функцию/метод НА ИМПОРТИРОВАННОМ МОДУЛЕ
        # (ПРИМЕЧАНИЕ: Если 'download_latest_attachment' не существует,
        # вам нужно будет проверить имя функции в 'imap_service.py')
        filepath = await asyncio.to_thread(
            imap_service.download_latest_attachment,
            subject_filter=SUBJECT_FILTER_DISLOCATION,
            sender_filter=SENDER_FILTER_DISLOCATION,
            filename_pattern=FILENAME_PATTERN_DISLOCATION
        )

        if filepath:
            logger.info(f"Обнаружен новый файл дислокации: {filepath}")
            try:
                # 1. Обрабатываем файл
                processed_count = await process_dislocation_file(filepath)
                
                # 2. Рассылаем уведомления (если что-то обработано)
                if processed_count > 0:
                    logger.info(f"Обработано {processed_count} записей. Запуск немедленной рассылки...")
                    # --- ИСПРАВЛЕНИЕ ВЫЗОВА:
                    service = notification_service.NotificationService(bot_instance)
                    await service.send_aggregated_train_event_notifications()
                else:
                    logger.info("Файл дислокации не привел к изменениям, рассылка не требуется.")
                
            except Exception as e:
                logger.error(f"❌ Ошибка обработки файла дислокации {filepath}: {e}", exc_info=True)
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"[Dislocation Import] Временный файл {os.path.basename(filepath)} удален.")
        else:
            logger.info("📬 [Dislocation] Новых файлов дислокации не найдено.")

    except AttributeError as e:
        # --- (НОВЫЙ БЛОК) Ловим ошибку 'download_latest_attachment' ---
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА: {e}")
        logger.error("     Возможно, функция 'download_latest_attachment' в 'imap_service.py' называется иначе?")
        # ---
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_process_dislocation: {e}", exc_info=True)
        # Не "raise e", чтобы не остановить планировщик