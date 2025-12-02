# services/dislocation_importer.py

import pandas as pd
import asyncio
import re
import os
from typing import Optional, Dict, List, Any
from sqlalchemy.future import select
from sqlalchemy import update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime

# --- Импорты из вашего проекта ---
from db import SessionLocal
# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
from models import Tracking, TrainEventLog, Train 
from model.terminal_container import TerminalContainer 
from logger import get_logger 
from telegram import Bot
from services.imap_service import ImapService 
from services import notification_service 
from services.train_event_notifier import process_dislocation_for_train_events
# --- ✅ ИМПОРТ ФУНКЦИИ ОБНОВЛЕНИЯ ---
from queries.train_queries import update_train_status_from_tracking_data

logger = get_logger(__name__) 

# --- ОПРЕДЕЛЯЕМ ПАПКУ ДЛЯ ЗАГРУЗОК ---
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# ---

# =========================================================================
# === 1. КАРТА СОПОСТАВЛЕНИЯ (без изменений) ===
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
# === 2. ХЕЛПЕРЫ (без изменений) ===
# =========================================================================

def _fill_empty_rows_with_previous(df: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """Заполняет пустые значения в указанном столбце предыдущими значениями."""
    df[column_name] = df[column_name].ffill()
    return df

# =========================================================================
# === 3. "УМНЫЙ" ЧИТАТЕЛЬ ФАЙЛОВ (без изменений) ===
# =========================================================================

def _read_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """
    Считывает данные из .xlsx файла дислокации от РЖД.
    """
    logger.info(f"Чтение файла дислокации: {filepath}")
    
    try:
        excel_cols_as_str = [
            'Грузоотправитель (ТГНЛ)', 'Грузоотправитель (ОКПО)', 'Грузоотправитель (наим)',
            'Грузополучатель (ТГНЛ)', 'Грузополучатель (ОКПО)', 'Грузополучатель (наим)',
            'Код груза ГНГ', 'Номер поезда', 'Номер вагона', 'Номер накладной',
            'Идентификатор отправки', 'Грузоотправитель', 'Грузополучатель',
            'Индекс поезда с наименованиями станций'
        ]
        dtype_map = {col: str for col in excel_cols_as_str}
        
        df = pd.read_excel(filepath, skiprows=3, header=0, engine='openpyxl', dtype=dtype_map)
        
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
# === 4. ✅ ОБНОВЛЕННАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ ТАБЛИЦЫ TRAIN ===
# =========================================================================

async def update_train_statuses_from_tracking(
    session: AsyncSession, 
    processed_tracking_objects: List[Tracking]
):
    """
    Агрегирует данные из Tracking и обновляет таблицу 'Train'.
    Вызывается ВНУТРИ сессии process_dislocation_file.
    """
    logger.info(f"[TrainTable] Запуск обновления статусов поездов для {len(processed_tracking_objects)} записей.")
    
    # 1. Находим последнюю операцию для каждого КОНТЕЙНЕРА из обработанных
    container_latest_op: Dict[str, Tracking] = {}
    for tracking_obj in processed_tracking_objects:
        # Убедимся, что у объекта есть дата, иначе он бесполезен для сортировки
        op_date = tracking_obj.operation_date
        if not op_date:
            continue
            
        container_num = tracking_obj.container_number
        # Обновляем, только если дата новее или ее не было
        if container_num not in container_latest_op or op_date > container_latest_op[container_num].operation_date:
            container_latest_op[container_num] = tracking_obj
    
    if not container_latest_op:
        logger.info("[TrainTable] Нет данных для обновления статусов поездов.")
        return 0

    # 2. Находим связь Контейнер -> Терминальный Поезд (K25-xxx)
    container_keys = list(container_latest_op.keys())
    result = await session.execute(
        select(TerminalContainer.container_number, TerminalContainer.train)
        .where(TerminalContainer.container_number.in_(container_keys))
        .where(TerminalContainer.train.isnot(None))
    )
    
    # Создаем карту: {'контейнер': 'K25-103'}
    container_to_train_map: Dict[str, str] = {row[0]: row[1] for row in result.all()}

    # 3. Агрегируем по ТЕРМИНАЛЬНОМУ ПОЕЗДУ
    # Нам нужна последняя операция для каждого *поезда*
    train_latest_op: Dict[str, Tracking] = {}
    
    for container_num, tracking_obj in container_latest_op.items():
        terminal_train_num = container_to_train_map.get(container_num)
        
        # Если этот контейнер не привязан к поезду (K25-xxx), пропускаем
        if not terminal_train_num:
            continue
            
        if terminal_train_num not in train_latest_op:
            train_latest_op[terminal_train_num] = tracking_obj
        else:
            # Ищем самую свежую операцию среди всех контейнеров этого поезда
            current_latest_date = train_latest_op[terminal_train_num].operation_date
            if tracking_obj.operation_date and (current_latest_date is None or tracking_obj.operation_date > current_latest_date):
                train_latest_op[terminal_train_num] = tracking_obj

    if not train_latest_op:
        logger.info("[TrainTable] Нет отслеживаемых поездов (K25-xxx) в этом обновлении.")
        return 0

    logger.info(f"[TrainTable] Найдены {len(train_latest_op)} уникальных поездов для обновления: {list(train_latest_op.keys())}")

    # 4. Обновляем таблицу 'Train'
    updated_train_count = 0
    for terminal_train_number, latest_tracking_obj in train_latest_op.items():
        try:
            # --- ✅ ИЗМЕНЕНИЕ: Передаем сессию ---
            success = await update_train_status_from_tracking_data(
                terminal_train_number, 
                latest_tracking_obj,
                session=session # <--- ПЕРЕДАЕМ СЕССИЮ
            )
            if success:
                updated_train_count += 1
        except Exception as e:
            logger.error(f"[TrainTable] Не удалось обновить статус для поезда {terminal_train_number}: {e}", exc_info=True)

    logger.info(f"[TrainTable] Успешно обновлены статусы для {updated_train_count} поездов.")
    return updated_train_count


# =========================================================================
# === 5. ОБНОВЛЕННЫЙ УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ДЛЯ БД ===
# =========================================================================

async def process_dislocation_file(filepath: str):
    """
    Обрабатывает файл дислокации, обновляет/вставляет данные в БД
    и запускает обновление таблицы Train.
    """
    
    df = await asyncio.to_thread(_read_excel_data, filepath)
    if df is None:
        logger.warning(f"Файл {filepath} не был обработан, dataframe пуст или не распознан формат.")
        return 0

    data_rows = df.to_dict('records') 
    
    updated_count = 0
    inserted_count = 0
    
    # --- ✅ Список для сбора обновленных ОБЪЕКТОВ Tracking ---
    processed_tracking_objects: List[Tracking] = []

    session = SessionLocal()
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

            STRING_COLS_TO_CONVERT = [
                'sender_tgnl', 'sender_okpo', 'sender_name',
                'receiver_tgnl', 'receiver_okpo', 'receiver_name',
                'cargo_gng_code', 'train_number', 'wagon_number', 'waybill',
                'dispatch_id', 'sender_name_short', 'receiver_name_short',
                'train_index_full'
            ]
            dt_format_with_time = '%d.%m.%Y %H:%M'
            dt_format_date_only = '%d.%m.%Y'


            for row_data in data_rows:
                
                container_number = row_data.get('container_number')
                if not container_number:
                    continue

                # --- Приведение типов (без изменений) ---
                if 'is_loaded_trip' in row_data and row_data['is_loaded_trip'] is not None:
                    row_data['is_loaded_trip'] = bool(row_data['is_loaded_trip'])
                
                for date_col in ['operation_date', 'trip_start_datetime', 'trip_end_datetime', 'delivery_deadline']:
                    if date_col in row_data and row_data[date_col] is not None:
                        if pd.isna(row_data[date_col]):
                            row_data[date_col] = None
                            continue
                        
                        try:
                            py_dt = datetime.strptime(str(row_data[date_col]), dt_format_with_time)
                            row_data[date_col] = py_dt
                        except ValueError:
                            try:
                                py_dt = datetime.strptime(str(row_data[date_col]), dt_format_date_only)
                                row_data[date_col] = py_dt
                            except Exception as e:
                                try:
                                    py_dt = pd.to_datetime(row_data[date_col], dayfirst=True).to_pydatetime()
                                    if py_dt.tzinfo:
                                        py_dt = py_dt.replace(tzinfo=None)
                                    row_data[date_col] = py_dt
                                except Exception as e_pandas:
                                    logger.warning(f"Не удалось распознать дату '{row_data[date_col]}' для {container_number}: {e_pandas}")
                                    row_data[date_col] = None

                for key in ['cargo_weight_kg', 'total_distance', 'distance_traveled', 'km_left']:
                    if key in row_data and row_data[key] is not None:
                        try:
                            row_data[key] = int(row_data[key])
                        except (ValueError, TypeError):
                            row_data[key] = None 
                
                for col_name in STRING_COLS_TO_CONVERT:
                    if col_name in row_data and row_data[col_name] is not None:
                        row_data[col_name] = str(row_data[col_name]).removesuffix('.0')
                
                # --- Конец приведения типов ---
                
                existing_entry = tracking_map.get(container_number)
                new_operation_date = row_data.get('operation_date') 
                
                if existing_entry:
                    # =====================================================
                    # 🔥 ЛОГИКА "ЗАМОРОЗКИ" (Фильтр завершенного рейса) 🔥
                    # =====================================================
                    
                    # Проверяем текущее состояние в БД
                    db_curr_station = (existing_entry.current_station or "").strip().lower()
                    db_dest_station = (existing_entry.to_station or "").strip().lower()
                    db_operation = (existing_entry.operation or "").strip().lower()
                    
                    # Флаг: контейнер УЖЕ выгружен на станции назначения
                    is_already_completed = False
                    if db_curr_station and db_dest_station:
                         # Если станции совпадают И операция содержит "выгрузка"
                         if db_curr_station == db_dest_station and "выгрузка" in db_operation:
                             is_already_completed = True

                    if is_already_completed:
                        # Проверяем, не является ли новая строка началом НОВОГО рейса
                        new_waybill = row_data.get('waybill')
                        new_dest = row_data.get('to_station')
                        
                        is_new_trip = False
                        
                        # Если изменилась накладная -> Новый рейс
                        if new_waybill and existing_entry.waybill and new_waybill != existing_entry.waybill:
                            is_new_trip = True
                            
                        # Если изменилась станция назначения -> Новый рейс
                        elif new_dest and existing_entry.to_station and new_dest != existing_entry.to_station:
                            is_new_trip = True
                            
                        # Если это НЕ новый рейс, а "хвост" старого (Вывоз/Завоз) -> ИГНОРИРУЕМ
                        if not is_new_trip:
                            # logger.debug(f"Пропуск обновления для {container_number}: рейс завершен (Выгрузка на назначении).")
                            continue 
                    
                    # =====================================================
                    
                    # --- ЛОГИКА ОБНОВЛЕНИЯ ---
                    current_date = existing_entry.operation_date 
                    
                    if new_operation_date and (current_date is None or new_operation_date > current_date):
                        for key, value in row_data.items():
                            setattr(existing_entry, str(key), value)
                        
                        updated_count += 1
                        processed_tracking_objects.append(existing_entry) # <--- ✅ Сбор данных
                else:
                    # --- ЛОГИКА СОЗДАНИЯ ---
                    new_entry_data = {str(k): v for k, v in row_data.items()}
                    new_entry = Tracking(**new_entry_data) 
                    session.add(new_entry)
                    tracking_map[container_number] = new_entry 
                    
                    inserted_count += 1
                    processed_tracking_objects.append(new_entry) # <--- ✅ Сбор данных
        
        logger.info(f"Успешно сохранено в БД Tracking: {inserted_count} новых, {updated_count} обновленных.")
        
        # --- ✅ ВЫЗОВ ОБНОВЛЕНИЯ ТАБЛИЦЫ TRAIN (перед коммитом) ---
        if processed_tracking_objects:
            # Передаем сессию
            await update_train_statuses_from_tracking(session, processed_tracking_objects)
        # ---
        
        await session.commit()
        
        # --- Логика событий поезда (вызывается ПОСЛЕ коммита) ---
        if inserted_count > 0 or updated_count > 0:
            logger.info(f"Запуск анализа событий поезда для {len(data_rows)} записей...")
            try:
                # Эта функция сама откроет сессию и запишет события в TrainEventLog
                await process_dislocation_for_train_events(data_rows)
            except Exception as e_event:
                logger.error(f"Ошибка при логировании событий поезда: {e_event}", exc_info=True)

        
    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка при сохранении в БД: {e}", exc_info=True)
        return 0 
    finally:
        await session.close()

    logger.info(f"[Dislocation Import] Обработка {filepath} завершена.")
    return inserted_count + updated_count


# =========================================================================
# === 6. ФУНКЦИЯ, ВЫЗЫВАЕМАЯ ПЛАНИРОВЩИКОМ (с гибким фильтром) ===
# =========================================================================

# --- ✅ ОБНОВЛЕННЫЙ ГИБКИЙ ФИЛЬТР ---
# Ищет "Отчёт" + (1+ пробел) + "слежения" + (1+ пробел) + "TrackerBot" + (0+ пробелов) + "№"
# Это позволяет находить "Ошибка...Отчёт слежения..." и "Отчёт  слежения TrackerBot№"
SUBJECT_FILTER_DISLOCATION = r'Отчёт\s+слежения\s+TrackerBot\s*№'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru'
FILENAME_PATTERN_DISLOCATION = r'\.(xlsx|xls)$' # Допускаем оба расширения

async def check_and_process_dislocation(bot_instance: Bot):
    """Проверяет почту, обрабатывает файлы и рассылает уведомления."""
    
    logger.info("Scheduler: Запуск проверки дислокации...")
    try:
        imap = ImapService()
        
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            subject_filter=SUBJECT_FILTER_DISLOCATION, # <--- Использует новый гибкий фильтр
            sender_filter=SENDER_FILTER_DISLOCATION,
            filename_pattern=FILENAME_PATTERN_DISLOCATION
        )

        if filepath:
            logger.info(f"Обнаружен новый файл дислокации: {filepath}")
            try:
                # 1. Обрабатываем файл (Обновляет Tracking И Train)
                processed_count = await process_dislocation_file(filepath)
                
                # 2. Рассылаем уведомления (если что-то обработано)
                if processed_count > 0:
                    logger.info(f"Обработано {processed_count} записей. Запуск немедленной рассылки...")
                    service = notification_service.NotificationService(bot_instance)
                    # Эта функция отправляет админу события из TrainEventLog
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
        # Не "raise e", чтобы не остановить планировщик