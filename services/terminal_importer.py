# services/terminal_importer.py
from __future__ import annotations

import asyncio
import os
import re
from typing import List, Tuple, Optional, Dict, Any
import pandas as pd
from sqlalchemy import select, update, insert
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from logger import get_logger
from model.terminal_container import TerminalContainer
from db import SessionLocal
from services.imap_service import ImapService

logger = get_logger(__name__)
imap_service = ImapService()
DOWNLOAD_DIR_TERMINAL = "downloads/terminal"

# --- ОБНОВЛЕННЫЕ КОНСТАНТЫ IMAP ДЛЯ ОТЧЕТА ТЕРМИНАЛА (более мягкие) ---
# Ищет "Executive summary" в любом месте темы (регистронезависимо)
SUBJECT_FILTER_TERMINAL = r'executive\s*summary' 
# Отправитель остается строгим (почтовый адрес должен быть точным)
SENDER_FILTER_TERMINAL = 'aterminal@effex.ru' 
# Ищет "A-Terminal" в любом месте имени файла (регистронезависимо), допуская xlsx/xls
FILENAME_PATTERN_TERMINAL = r'A-Terminal.*\.(xlsx|xls)$'
# ----------------------------------------------------------------------

# ✅ ФИНАЛЬНЫЙ СЛОВАРЬ СОПОСТАВЛЕНИЯ (на основе вашего списка столбцов)
# Ключи - точные названия из Excel-файла
TERMINAL_COLUMN_MAPPING = {
    'Контейнер': 'container_number',
    'Клиент': 'client',
    'Состояние': 'status',     # Используем "Состояние" вместо "Статус"
    'Принят': 'accept_datetime', # Временный ключ, т.к. в БД два поля (date и time)
}

# --- Вспомогательные функции ---

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """
    Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ со смещением.
    """
    tz = ZoneInfo("Asia/Vladivostok")
    target_date = datetime.now(tz) - timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")

def extract_train_code_from_filename(filename: str) -> str | None:
    """Извлекаем код поезда из имени файла."""
    if not filename: return None
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    m = re.search(r"([КK]\s*\d{2}[-–— ]?\s*\d{3})", name, flags=re.IGNORECASE)
    if not m: return None
    code = m.group(1).upper().replace("K", "К").replace(" ", "").replace("–", "-").replace("—", "-")
    return code


def normalize_container(value) -> str | None:
    """
    Нормализует номер контейнера: убирает пробелы, приводит к верхнему регистру, убирает .0
    """
    if pd.isna(value) or value is None: return None
    s = str(value).strip().upper()
    if s.endswith('.0'): s = s[:-2]
    # Дополнительно убираем все небуквенно-цифровые символы на всякий случай
    s = re.sub(r'[^A-Z0-9]', '', s)
    return s if s else None


def find_container_column(df: pd.DataFrame) -> str | None:
    """Пытаемся найти колонку с номерами контейнеров."""
    candidates = ["контейнер", "container", "container no", "container no.",
                  "номер контейнера", "№ контейнера", "номенклатура"]

    # Ищем точное совпадение "Контейнер" сначала
    for col in df.columns:
        if str(col).strip() == "Контейнер":
            return col

    # Если не нашли, ищем по вариантам
    # ✅ ИСПРАВЛЕНИЕ PYLANCE (строка 115): Явно приводим к str для ключей и значений
    cols_norm = {str(c).strip().lower(): str(c) for c in df.columns}
    for cand in candidates:
        if cand in cols_norm:
             return cols_norm[cand]

    # Ищем по частичному совпадению (менее надежно)
    for col in df.columns:
        name = str(col).strip().lower()
        if name.startswith("contain") or "контейнер" in name:
            return col

    return None

def normalize_client_name(value) -> str | None:
    """Нормализует имя клиента."""
    if pd.isna(value) or value is None: return None
    s = str(value).strip()
    return s if s else None


def _read_terminal_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """Считывает данные из Excel-файла отчета A-Terminal, ища лист 'Loaded...'."""
    try:
        xl = pd.ExcelFile(filepath)
        sheet_names = xl.sheet_names
        target_sheet_name = None

        # 1. Поиск листа, начинающегося с "Loaded"
        for name in sheet_names:
            if name.strip().lower().startswith('loaded'):
                target_sheet_name = name
                break

        if not target_sheet_name:
            logger.warning(f"[Terminal Report] Лист, начинающийся с 'Loaded', не найден в файле {os.path.basename(filepath)}. Пропускаю.")
            return None

        # 2. Считывание данных с найденного листа
        # header=0 означает, что первая строка - это заголовки
        df = pd.read_excel(xl, sheet_name=target_sheet_name, header=0)

        # 3. Очистка имен колонок (убираем только лишние пробелы)
        df.columns = [str(c).strip() for c in df.columns] 
        df = df.dropna(how='all') # Удаляем полностью пустые строки

        # 4. Выбираем только нужные столбцы из TERMINAL_COLUMN_MAPPING
        required_cols = list(TERMINAL_COLUMN_MAPPING.keys())
        
        # ✅ ИСПРАВЛЕНИЕ PYLANCE (строка 183): Создаем список строковых имен колонок для безопасного сравнения
        df_columns_str = [str(c) for c in df.columns] 
        existing_required_cols = [col for col in required_cols if col in df_columns_str] 

        # Проверяем наличие 'Контейнер'
        if 'Контейнер' not in existing_required_cols:
             logger.error(f"❌ [Terminal Report] В файле {os.path.basename(filepath)} на листе '{target_sheet_name}' не найден столбец 'Контейнер'.")
             return None

        df = df[existing_required_cols] 

        return df
    except Exception as e:
        logger.error(f"❌ Ошибка чтения Excel-файла A-Terminal {filepath}: {e}", exc_info=True)
        return None


async def process_terminal_report_file(filepath: str) -> Dict[str, int]:
    """
    Обрабатывает один файл отчета терминала, обновляя или создавая записи в TerminalContainer.
    """
    logger.info(f"[Terminal Report] Начало обработки файла: {os.path.basename(filepath)}")

    df = await asyncio.to_thread(_read_terminal_excel_data, filepath)
    if df is None or df.empty:
        logger.warning(f"[Terminal Report] Файл {os.path.basename(filepath)} пуст, не содержит данных или нужных столбцов.")
        return {'updated': 0, 'added': 0}

    records_to_process = df.to_dict('records')
    updated_count = 0
    added_count = 0

    async with SessionLocal() as session:
        async with session.begin():
            for record in records_to_process:
                container_number_raw = record.get('Контейнер')

                # ✅ Используем `normalize_container` для стандартизации номера
                container_number = normalize_container(container_number_raw)

                if not container_number:
                    continue

                cleaned_record_for_db = {}
                # key_excel - это "Контейнер", "Клиент", "Состояние", "Принят"
                for key_excel, value in record.items():
                    # Проверяем, что ключ есть в маппинге и значение не пустое
                    if key_excel in TERMINAL_COLUMN_MAPPING and pd.notna(value):

                        mapped_key_db = TERMINAL_COLUMN_MAPPING[key_excel]

                        # ✅ Особая обработка даты/времени из "Принят"
                        if mapped_key_db == 'accept_datetime':
                            try:
                                # Пытаемся распознать дату и время
                                if isinstance(value, datetime):
                                    cleaned_record_for_db['accept_date'] = value.date()
                                    cleaned_record_for_db['accept_time'] = value.time()
                                elif isinstance(value, date): # Если только дата
                                    cleaned_record_for_db['accept_date'] = value
                                elif isinstance(value, time): # Если только время
                                     cleaned_record_for_db['accept_time'] = value
                                elif isinstance(value, (str, int, float)): # Пытаемся распарсить строку/число
                                    # Эта строка может потребовать адаптации под ваш точный формат в Excel
                                    dt = pd.to_datetime(value)
                                    cleaned_record_for_db['accept_date'] = dt.date()
                                    cleaned_record_for_db['accept_time'] = dt.time()
                            except Exception as dt_err:
                                logger.warning(f"Не удалось распознать дату/время '{value}' для {container_number}: {dt_err}")
                            continue # Переходим к следующему полю

                        # Пропускаем 'container_number', он пойдет отдельно
                        elif mapped_key_db == 'container_number':
                            continue

                        # Нормализуем клиента
                        elif mapped_key_db == 'client':
                            cleaned_record_for_db[mapped_key_db] = normalize_client_name(value)
                        # Остальные поля
                        else:
                            cleaned_record_for_db[mapped_key_db] = value

                # Пропускаем, если в словаре нет ничего полезного
                if not cleaned_record_for_db:
                    continue

                # 1. Попытка обновить (UPDATE) существующий контейнер
                update_stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == container_number
                ).values(**cleaned_record_for_db)

                result = await session.execute(update_stmt)

                if result.rowcount > 0:
                    updated_count += 1
                else:
                    # 2. Если не обновили (не нашли), то вставляем новую запись (INSERT)
                    # Добавляем container_number, который был обработан отдельно
                    cleaned_record_for_db['container_number'] = container_number
                    insert_stmt = insert(TerminalContainer).values(**cleaned_record_for_db)
                    try:
                        await session.execute(insert_stmt)
                        added_count += 1
                    except SQLAlchemyError as e:
                        # Ловим ошибку, если контейнер уже существует (например, из-за гонки потоков)
                        await session.rollback() # Откатываем транзакцию для этой строки
                        logger.warning(f"Ошибка INSERT для {container_number} (возможно, уже существует): {e}. Попытка UPDATE...")
                        # Попробуем обновить еще раз на всякий случай
                        try:
                             update_stmt_retry = update(TerminalContainer).where(
                                 TerminalContainer.container_number == container_number
                             ).values(**cleaned_record_for_db)
                             result_retry = await session.execute(update_stmt_retry)
                             if result_retry.rowcount > 0:
                                 updated_count += 1
                                 logger.info(f"Контейнер {container_number} успешно обновлен после ошибки INSERT.")
                             else:
                                 logger.error(f"Не удалось ни вставить, ни обновить {container_number} после ошибки INSERT.")
                        except Exception as update_err:
                             logger.error(f"Ошибка при повторном UPDATE для {container_number}: {update_err}")
                        await session.begin() # Начинаем новую "мини-транзакцию" для следующей строки

        logger.info(f"✅ [Terminal Report] Обновление завершено. Добавлено: {added_count}, Обновлено: {updated_count}.")

    return {'updated': updated_count, 'added': added_count}


# --- Функции импорта файла поезда ---

async def _collect_containers_from_excel(file_path: str) -> Dict[str, str]:
    """
    Читает Excel (для файла поезда) и возвращает словарь {container_number: client_name}.
    """
    xl = pd.ExcelFile(file_path)
    container_client_map: Dict[str, str] = {}

    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet)
            df.columns = [str(c).strip() for c in df.columns]

            container_col_header = find_container_column(df) # Ищет 'Контейнер' и другие варианты

            CLIENT_COLUMN_INDEX = 11 # L-колонка для клиента (индекс 11)
            if CLIENT_COLUMN_INDEX >= len(df.columns):
                logger.warning(f"[train_importer] На листе '{sheet}' нет колонки {CLIENT_COLUMN_INDEX+1} (Клиент). Пропускаю.")
                continue

            # Получаем имя столбца клиента по индексу
            client_col_header = df.columns[CLIENT_COLUMN_INDEX]

            if not container_col_header:
                logger.warning(f"[train_importer] На листе '{sheet}' не найдена колонка контейнеров ('Контейнер' или похожая). Пропускаю.")
                continue

            for _, row in df.iterrows():
                # ✅ Используем normalize_container для стандартизации
                cn = normalize_container(row.get(container_col_header))
                client = normalize_client_name(row.get(client_col_header))

                if cn and client:
                    # ✅ ИСПРАВЛЕНИЕ PYLANCE (строка 393): Гарантируем, что значение - str.
                    container_client_map[cn] = str(client) 
        except Exception as e:
            logger.error(f"[train_importer] Ошибка при чтении листа '{sheet}': {e}", exc_info=True)

    return container_client_map


async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    """Проставляет номер поезда и клиента в terminal_containers."""
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(f"Не удалось извлечь номер поезда из имени файла: {os.path.basename(src_file_path)}")

    container_client_map = await _collect_containers_from_excel(src_file_path)
    total_in_file = len(container_client_map)

    if total_in_file == 0:
        logger.warning(f"[train_importer] В файле поезда '{os.path.basename(src_file_path)}' нет распознанных контейнеров.")
        return 0, 0, train_code

    updated = 0
    try:
        async with SessionLocal() as session:
            async with session.begin(): # Используем транзакцию
                # `cn` здесь уже нормализован (UPPER, no spaces, no .0)
                for cn, client_name in container_client_map.items():

                    # `client_name` также нормализован (strip)
                    update_stmt = update(TerminalContainer).where(
                        TerminalContainer.container_number == cn
                    ).values(
                        train=train_code,
                        client=client_name
                    )

                    result = await session.execute(update_stmt)
                    updated += result.rowcount

            # Коммит произойдет автоматически

        logger.info(f"✅ [train_importer] Поезд {train_code}: обновлено {updated} из {total_in_file} (найденных в файле).")
        return updated, total_in_file, train_code

    except SQLAlchemyError as e:
        logger.error(f"[train_importer] Ошибка БД при импорте поезда {train_code}: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"[train_importer] Неожиданная ошибка при импорте поезда {train_code}: {e}", exc_info=True)
        raise


async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    """
    Функция для scheduler (ежедневная проверка почты).
    Ищет отчет Executive summary за сегодня или вчера.
    """
    logger.info("[Terminal Import] Проверка почты на наличие отчета терминала...")
    filepath = None
    stats = None
    
    # 1. Поиск отчета за сегодня
    today_str = _get_vladivostok_date_str(days_offset=0)
    # ✅ ИСПРАВЛЕНИЕ PYLANCE: Используем fr-строку для корректной обработки \s*
    subject_today = fr"{SUBJECT_FILTER_TERMINAL}\s*{today_str}"
    logger.info(f"Ищу '{subject_today}'...")
    filepath = await asyncio.to_thread(
        imap_service.download_latest_attachment,
        subject_filter=subject_today,
        sender_filter=SENDER_FILTER_TERMINAL,
        filename_pattern=FILENAME_PATTERN_TERMINAL
    )

    # 2. Поиск отчета за вчера, если сегодня не найден
    if not filepath:
        yesterday_str = _get_vladivostok_date_str(days_offset=1)
        # ✅ ИСПРАВЛЕНИЕ PYLANCE: Используем fr-строку для корректной обработки \s*
        subject_yesterday = fr"{SUBJECT_FILTER_TERMINAL}\s*{yesterday_str}"
        logger.info(f"Отчет за сегодня не найден. Ищу '{subject_yesterday}'...")
        filepath = await asyncio.to_thread(
            imap_service.download_latest_attachment,
            subject_filter=subject_yesterday,
            sender_filter=SENDER_FILTER_TERMINAL,
            filename_pattern=FILENAME_PATTERN_TERMINAL
        )

    if not filepath:
        logger.info("Актуальный файл 'Executive summary' не найден.")
        return {'file_name': 'Not found', 'sheets_processed': 0, 'total_added': 0}

    try:
        logger.info(f"Найден файл {filepath}. Запускаю импорт в terminal_containers...")
        # Вызываем основную логику обработки файла
        stats = await process_terminal_report_file(filepath) 
        
        # Добавляем имя файла в статистику для логирования/уведомления
        stats['file_name'] = os.path.basename(filepath)
        stats['sheets_processed'] = 1 
        stats['total_added'] = stats.get('added', 0)
        
        logger.info(f"Импорт из '{os.path.basename(filepath)}' завершен.")
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка при импорте файла '{filepath}': {e}", exc_info=True)
        # Бросаем исключение, чтобы job_daily_terminal_import уведомил админа
        raise
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)