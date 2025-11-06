# services/dislocation_importer.py

import pandas as pd
import asyncio
import re
import os
from typing import Optional, Dict
from sqlalchemy.future import select
from sqlalchemy import update, delete
from datetime import datetime

# --- Импорты из вашего проекта ---
from db import async_sessionmaker, SessionLocal # Импортируем SessionLocal
from models import Tracking, TrainEventLog
from logger import get_logger 
from telegram import Bot
from services.imap_service import ImapService # Импортируем КЛАСС
from services import notification_service # Для вызова уведомлений

logger = get_logger(__name__) 

# --- ОПРЕДЕЛЯЕМ ПАПКУ ДЛЯ ЗАГРУЗОК ---
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# ---

# =========================================================================
# === 1. КАРТА СОПОСТАВЛЕНИЯ ДЛЯ НОВОГО ФОРМАТА ===
# =========================================================================

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
    
    try:
        df = pd.read_excel(filepath, skiprows=3, header=0, engine='openpyxl')
        
        if 'Идентификатор отправки' in df.columns or 'Тип контейнера' in df.columns:
            logger.info(f"Обнаружен НОВЫЙ формат дислокации (РЖД, 45 столбцов).")
            
            valid_columns = [col for col in df.columns if col in COLUMN_MAPPING_RZD_NEW]
            if not valid_columns:
                logger.error("Новый формат распознан, но не найдено столбцов из COLUMN_MAPPING_RZD_NEW.")
                return None
            df = df[valid_columns]
            
            df.rename(columns=COLUMN_MAPPING_RZD_NEW, inplace=True)
            
            if 'container_number' in df.columns:
                df = _fill_empty_rows_with_previous(df, 'container_number')
            else:
                logger.error("Критическая ошибка: 'Номер контейнера' не найден в НОВОМ файле.")
                return None

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
    
    df = await asyncio.to_thread(_read_excel_data, filepath)
    if df is None:
        logger.warning(f"Файл {filepath} не был обработан, dataframe пуст или не распознан формат.")
        return 0

    data_rows = df.to_dict('records') 
    
    updated_count = 0
    inserted_count = 0
    events_to_log = [] 

    # Используем фабрику сессий из db.py
    session = SessionLocal() # <--- ИСПРАВЛЕНО (используем SessionLocal)
    try:
        
        container_numbers_from_file = [
            row['container_number'] for row in data_rows if row.get('container_number')
        ]
        if not container_numbers_from_file:
            logger.warning(f"В файле {filepath} не найдено ни одной строки с номером контейнера.")
        else:
            existing_trackings = (await session.execute(
                select(Tracking).where(Tracking.container_number.in_(set(container_numbers_from_file)))
            )).scalars().all()
            tracking_map = {t.container_number: t for t in existing_trackings}

            for row_data in data_rows:
                
                container_number = row_data.get('container_number')
                if not container_number:
                    continue

                # --- Приведение типов ---
                if 'is_loaded_trip' in row_data and row_data['is_loaded_trip'] is not None:
                    row_data['is_loaded_trip'] = bool(row_data['is_loaded_trip'])
                
                for date_col in ['operation_date', 'trip_start_datetime', 'trip_end_datetime', 'delivery_deadline']:
                    if date_col in row_data and row_data[date_col] is not None:
                        if pd.isna(row_data[date_col]):
                            row_data[date_col] = None
                        else:
                            try:
                                # Преобразуем в python datetime
                                py_dt = pd.to_datetime(row_data[date_col]).to_pydatetime()
                                # Убираем tzinfo, если оно есть, т.к. в БД колонка без timezone
                                if py_dt.tzinfo:
                                    py_dt = py_dt.replace(tzinfo=None)
                                row_data[date_col] = py_dt
                            except:
                                row_data[date_col] = None

                for key in ['cargo_weight_kg', 'total_distance', 'distance_traveled', 'km_left']:
                    if key in row_data and row_data[key] is not None:
                        try:
                            row_data[key] = int(row_data[key])
                        except (ValueError, TypeError):
                            row_data[key] = None 
                # --- Конец приведения типов ---

                existing_entry = tracking_map.get(container_number)
                new_operation_date = row_data.get('operation_date') 
                
                if existing_entry:
                    # --- ЛОГИКА ОБНОВЛЕНИЯ ---
                    current_date = existing_entry.operation_date 
                    if new_operation_date and (current_date is None or new_operation_date > current_date):
                        for key, value in row_data.items():
                            setattr(existing_entry, str(key), value)
                        
                        events_to_log.append(TrainEventLog(
                            container_number=container_number,
                            train_number=row_data.get('train_number', 'N/A'),
                            event_description=row_data.get('operation', 'Обновление'),
                            station=row_data.get('current_station', 'N/A'),
                            event_time=new_operation_date
                        ))
                        updated_count += 1
                else:
                    # --- ЛОГИКА СОЗДАНИЯ ---
                    new_entry_data = {str(k): v for k, v in row_data.items()}
                    new_entry = Tracking(**new_entry_data) 
                    session.add(new_entry)
                    tracking_map[container_number] = new_entry 
                    
                    events_to_log.append(TrainEventLog(
                        container_number=container_number,
                        train_number=row_data.get('train_number', 'N/A'),
                        event_description="Запись создана",
                        station=row_data.get('current_station', 'N/A'),
                        event_time=new_operation_date if new_operation_date else datetime.now()
                    ))
                    inserted_count += 1
                    
        if events_to_log:
            session.add_all(events_to_log)
        
        await session.commit()
        logger.info(f"Успешно сохранено в БД: {inserted_count} новых, {updated_count} обновленных.")
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка при сохранении в БД: {e}", exc_info=True)
        return 0
    finally:
        # Убедимся, что сессия закрыта
        await session.close()

    logger.info(f"[Dislocation Import] Обработка {filepath} завершена.")
    return inserted_count + updated_count


# =========================================================================
# === 5. ФУНКЦИЯ, ВЫЗЫВАЕМАЯ ПЛАНИРОВЩИКОМ (ИСПРАВЛЕНА) ===
# =========================================================================

# Фильтры из вашего repomix
SUBJECT_FILTER_DISLOCATION = r'^Отчёт слежения TrackerBot №'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru'
# --- ИСПРАВЛЕНИЕ: Допускаем .xls и .xlsx ---
FILENAME_PATTERN_DISLOCATION = r'\.(xlsx|xls)$' 

async def check_and_process_dislocation(bot_instance: Bot):
    """Проверяет почту, обрабатывает файлы и рассылает уведомления."""
    
    logger.info("Scheduler: Запуск проверки дислокации...")
    try:
        # --- ИСПРАВЛЕНИЕ ВЫЗОВА: ---
        # 1. Создаем ЭКЗЕМПЛЯР класса (без аргументов)
        #    Конструктор ImapService сам читает .env
        imap = ImapService()
        
        # 2. Вызываем МЕТОД на экземпляре
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            subject_filter=SUBJECT_FILTER_DISLOCATION,
            sender_filter=SENDER_FILTER_DISLOCATION,
            filename_pattern=FILENAME_PATTERN_DISLOCATION
        )
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        if filepath:
            logger.info(f"Обнаружен новый файл дислокации: {filepath}")
            try:
                # 1. Обрабатываем файл
                processed_count = await process_dislocation_file(filepath)
                
                # 2. Рассылаем уведомления (если что-то обработано)
                if processed_count > 0:
                    logger.info(f"Обработано {processed_count} записей. Запуск немедленной рассылки...")
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
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА: {e}")
        logger.error("     Убедитесь, что 'services/imap_service.py' содержит класс 'ImapService'.")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_process_dislocation: {e}", exc_info=True)
        # Не "raise e", чтобы не остановить планировщик тест
        