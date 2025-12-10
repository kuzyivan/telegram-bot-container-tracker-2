# services/terminal_importer.py
from __future__ import annotations

import logging
import os
import re
import asyncio
import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, Tuple, List

import pandas as pd
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# --- Импорты проекта ---
from db import SessionLocal
from services.imap_service import ImapService
from model.terminal_container import TerminalContainer
# Внимание: для работы с IMAP нужен этот импорт для критериев поиска
from imap_tools.query import AND

logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
DOWNLOAD_DIR = "download_container"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Настройки поиска писем (из старой версии)
SUBJECT_FILTER_TERMINAL = r'executive\s*summary'
SENDER_FILTER_TERMINAL = 'aterminal@effex.ru'
FILENAME_PATTERN_TERMINAL = r'\.(xlsx|xls)$'

# Маппинг столбцов для файла "Поезд" (train_importer logic)
# Используется в import_train_from_excel
CLIENT_COLUMN_INDEX = 11  # L-колонка

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (HELPER FUNCTIONS) ---

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ."""
    try:
        tz = ZoneInfo("Asia/Vladivostok")
    except Exception:
        # Fallback
        tz = datetime.timezone(datetime.timedelta(hours=10))
    target_date = datetime.datetime.now(tz) - timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")

def clean_string_value(val: Any) -> Optional[str]:
    """Преобразует значение в строку, корректно обрабатывая числа."""
    if pd.isna(val) or val == '' or str(val).lower() == 'nan':
        return None
    try:
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        if isinstance(val, (int, float)):
            return str(int(val))
    except Exception:
        pass
    return str(val).strip()

def normalize_container(value: Any) -> Optional[str]:
    """Нормализует номер контейнера: удаляет пробелы, .0, приводит к верхнему регистру."""
    s = clean_string_value(value)
    if not s:
        return None
    s = s.upper()
    # Удаляем все не буквенно-цифровые символы
    s = re.sub(r'[^A-Z0-9]', '', s)
    if len(s) == 11:
        return s
    return s if s else None

def normalize_client_name(value: Any) -> Optional[str]:
    """Нормализует имя клиента."""
    return clean_string_value(value)

def parse_date_safe(val: Any) -> Optional[datetime.date]:
    """Безопасный парсинг даты."""
    if pd.isna(val) or val == '': return None
    try:
        if isinstance(val, pd.Timestamp): return val.date()
        if isinstance(val, datetime.datetime): return val.date()
        if isinstance(val, str): return pd.to_datetime(val, dayfirst=True).date()
    except Exception: return None
    return None

def parse_time_safe(val: Any) -> Optional[datetime.time]:
    """Безопасный парсинг времени."""
    if pd.isna(val) or val == '': return None
    try:
        if isinstance(val, pd.Timestamp): return val.time()
        if isinstance(val, datetime.datetime): return val.time()
        if isinstance(val, datetime.time): return val
        if isinstance(val, str):
            # Пытаемся вытащить время из строки
            return pd.to_datetime(val, dayfirst=True).time()
    except Exception: return None
    return None

def parse_float_safe(val: Any) -> Optional[float]:
    """Безопасный парсинг числа."""
    if pd.isna(val) or val == '': return None
    try:
        if isinstance(val, (int, float)): return float(val)
        clean_val = str(val).replace(',', '.').replace('\xa0', '').strip()
        return float(clean_val)
    except Exception: return None

def extract_train_code_from_filename(filename: str) -> str | None:
    """Извлекает код поезда (К25-...) из имени файла."""
    if not filename: return None
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    # Ищем паттерн KXX-XXX или КXX-XXX
    m = re.search(r"([КK]\s*\d{2}[-–— ]?\s*\d{3})", name, flags=re.IGNORECASE)
    if not m: return None
    code = m.group(1).upper().replace("K", "К").replace(" ", "").replace("–", "-").replace("—", "-")
    return code

def find_container_column(df: pd.DataFrame) -> str | None:
    """Ищет колонку с номером контейнера в DataFrame."""
    candidates = ["контейнер", "container", "container no", "номер контейнера", "№ контейнера"]
    cols_norm = {str(c).strip().lower(): str(c) for c in df.columns}
    for cand in candidates:
        if cand in cols_norm:
            return cols_norm[cand]
    for col in df.columns:
        if "контейнер" in str(col).lower():
            return str(col)
    return None


# =========================================================================
# 1. ЛОГИКА ДЛЯ ПЛАНИРОВЩИКА (ПРОВЕРКА ПОЧТЫ И ЗАПУСК ИМПОРТА)
# =========================================================================

async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    """
    Основная функция для Scheduler.
    1. Подключается к почте.
    2. Ищет письмо с Executive summary за сегодня (или вчера).
    3. Скачивает файл.
    4. Запускает process_terminal_report_file для обновления БД.
    """
    imap = ImapService()
    filepath = None
    
    # 1. Поиск за СЕГОДНЯ
    today_str = _get_vladivostok_date_str(days_offset=0)
    logger.info(f"[Terminal Check] Ищу 'Executive summary' за {today_str}...")
    
    # Формируем фильтр темы (regex для imap_service)
    subject_regex_today = fr"{SUBJECT_FILTER_TERMINAL}.*{re.escape(today_str)}"
    
    filepath = await asyncio.to_thread(
        imap.download_latest_attachment,
        subject_filter=subject_regex_today,
        sender_filter=SENDER_FILTER_TERMINAL,
        filename_pattern=FILENAME_PATTERN_TERMINAL
    )

    # 2. Если не нашли, ищем за ВЧЕРА
    if not filepath:
        yesterday_str = _get_vladivostok_date_str(days_offset=1)
        logger.info(f"[Terminal Check] За сегодня нет. Ищу за вчера ({yesterday_str})...")
        subject_regex_yesterday = fr"{SUBJECT_FILTER_TERMINAL}.*{re.escape(yesterday_str)}"
        
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            subject_filter=subject_regex_yesterday,
            sender_filter=SENDER_FILTER_TERMINAL,
            filename_pattern=FILENAME_PATTERN_TERMINAL
        )

    if not filepath:
        logger.info("[Terminal Check] Актуальный файл терминала не найден.")
        return None

    # 3. Обработка файла
    stats = None
    try:
        logger.info(f"[Terminal Check] Файл найден: {filepath}. Запуск импорта в БД...")
        
        async with SessionLocal() as session:
            # Вызываем функцию парсинга и сохранения (новая логика)
            await process_terminal_report_file(session, filepath)
            
            # TODO: Можно доработать process_terminal_report_file чтобы он возвращал счетчики
            stats = {
                "file_name": os.path.basename(filepath),
                "status": "success",
                "total_added": "См. логи" 
            }
            
    except Exception as e:
        logger.error(f"❌ [Terminal Check] Ошибка при обработке файла: {e}", exc_info=True)
        stats = {"error": str(e)}
    finally:
        # Удаляем файл после обработки
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"[Terminal Check] Временный файл удален.")

    return stats


# =========================================================================
# 2. ЛОГИКА ОБРАБОТКИ ОТЧЕТА ТЕРМИНАЛА (НОВАЯ СТРУКТУРА БД)
# =========================================================================

async def process_terminal_report_file(session: AsyncSession, file_path: str):
    """
    Парсит Excel файл A-Terminal.
    Ожидает листы 'Arrival' (Прибытие) и 'Dispatch' (Отгрузка).
    """
    logger.info(f"[Import] Анализ Excel-файла: {file_path}")

    try:
        xls = pd.ExcelFile(file_path)
        sheet_names = xls.sheet_names
        logger.info(f"Найдены листы: {sheet_names}")

        processed_any = False

        # 1. Лист ARRIVAL
        arrival_sheet = next((s for s in sheet_names if "Arrival" in s), None)
        if arrival_sheet:
            logger.info(f"Обработка листа ПРИБЫТИЯ: {arrival_sheet}")
            df_arrival = pd.read_excel(xls, sheet_name=arrival_sheet, dtype=object)
            await _process_arrival_data(session, df_arrival)
            processed_any = True
        else:
            logger.warning("Лист 'Arrival' не найден.")

        # 2. Лист DISPATCH
        dispatch_sheet = next((s for s in sheet_names if "Dispatch" in s), None)
        if dispatch_sheet:
            logger.info(f"Обработка листа ОТГРУЗКИ: {dispatch_sheet}")
            df_dispatch = pd.read_excel(xls, sheet_name=dispatch_sheet, dtype=object)
            await _process_dispatch_data(session, df_dispatch)
            processed_any = True
        else:
            logger.warning("Лист 'Dispatch' не найден.")
        
        # Fallback: Если спец. листов нет, пробуем первый как общий сток
        if not processed_any:
            logger.warning("Специфичные листы не найдены. Обрабатываю первый лист как Arrival.")
            df_generic = pd.read_excel(xls, sheet_name=0, dtype=object)
            await _process_arrival_data(session, df_generic)

        logger.info("✅ Обработка файла завершена.")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка при обработке Excel: {e}", exc_info=True)
        raise e

async def _process_arrival_data(session: AsyncSession, df: pd.DataFrame):
    """
    Обработка данных ARRIVAL. Выполняет UPSERT (Вставка или Обновление).
    """
    df.columns = df.columns.str.strip()
    
    # Маппинг: Excel Column -> DB Field
    mapping = {
        'Терминал': 'terminal',
        'Контейнер': 'container_number',
        'Клиент': 'client',
        'ИНН': 'inn',
        'Краткое наименование': 'short_name',
        'Сток': 'stock',
        'Таможенный режим': 'customs_mode',
        'Направление': 'direction',
        'Тип': 'container_type',
        'Размер': 'size',
        'Тара': 'tare',
        'Брутто клиента': 'weight_client', 
        'Состояние': 'state',
        'Груз': 'cargo',
        'Пломбы': 'seals',
        'Принят': 'accept_date',
        # Транспортные поля входа
        'Id': 'in_id',
        'Транспорт': 'in_transport',
        'Номер вагона | Номер тягача': 'in_number',
        'Станция | Водитель': 'in_driver'
    }

    processed_rows = []
    
    for _, row in df.iterrows():
        # Ищем номер контейнера
        cont_val = row.get('Контейнер')
        container_number = normalize_container(cont_val)
        
        if not container_number:
            continue

        data = {}
        # Заполняем данные
        for xls_col, db_col in mapping.items():
            val = row.get(xls_col)
            
            if db_col in ['tare', 'weight_client']:
                data[db_col] = parse_float_safe(val)
            elif db_col == 'accept_date':
                # 'Принят' обычно содержит дату и время
                data['accept_date'] = parse_date_safe(val)
                data['accept_time'] = parse_time_safe(val)
            elif db_col == 'container_number':
                continue # Уже обработали
            else:
                data[db_col] = clean_string_value(val)

        # Обязательные поля и дефолты
        data['container_number'] = container_number
        if not data.get('terminal'):
            data['terminal'] = 'A-Terminal'
        
        # Статус по умолчанию для прибывших
        data['status'] = 'ARRIVED'
        
        processed_rows.append(data)

    if processed_rows:
        await _bulk_upsert_arrival(session, processed_rows)

async def _process_dispatch_data(session: AsyncSession, df: pd.DataFrame):
    """
    Обработка данных DISPATCH. Только UPDATE существующих (проставляем дату убытия).
    """
    df.columns = df.columns.str.strip()

    # Проверка наличия колонки даты убытия
    if 'Отправлен' not in df.columns:
        logger.warning("В листе Dispatch нет колонки 'Отправлен'. Пропуск.")
        return

    processed_rows = []

    for _, row in df.iterrows():
        container_number = normalize_container(row.get('Контейнер'))
        if not container_number:
            continue

        # Данные для обновления
        data = {
            'container_number': container_number,
            'status': 'DISPATCHED', # Меняем статус
            'updated_at': datetime.datetime.now()
        }

        # Дата убытия
        out_val = row.get('Отправлен')
        data['dispatch_date'] = parse_date_safe(out_val)
        data['dispatch_time'] = parse_time_safe(out_val)

        # Поля выхода (обычно имеют суффикс .1 в pandas, если имена дублируются с входом)
        # Если заголовки уникальны в файле, суффикса не будет. Проверяем оба варианта.
        data['out_id'] = clean_string_value(row.get('Id.1') or row.get('Id'))
        data['out_transport'] = clean_string_value(row.get('Транспорт.1') or row.get('Транспорт'))
        data['out_number'] = clean_string_value(row.get('Номер вагона | Номер тягача.1') or row.get('Номер вагона | Номер тягача'))
        data['out_driver'] = clean_string_value(row.get('Станция | Водитель.1') or row.get('Станция | Водитель'))

        processed_rows.append(data)

    if processed_rows:
        await _bulk_update_dispatch(session, processed_rows)

# --- SQL ЗАПРОСЫ (RAW) ---

async def _bulk_upsert_arrival(session: AsyncSession, rows: List[dict]):
    """Выполняет массовый INSERT ... ON CONFLICT DO UPDATE для прибытия."""
    if not rows: return
    
    # Используем raw SQL для производительности и гибкости upsert
    stmt = text("""
        INSERT INTO terminal_containers (
            terminal, container_number, client, inn, short_name, stock,
            customs_mode, direction, container_type, size, tare, weight_client,
            state, cargo, seals, accept_date, accept_time,
            in_id, in_transport, in_number, in_driver, status, updated_at, created_at
        ) VALUES (
            :terminal, :container_number, :client, :inn, :short_name, :stock,
            :customs_mode, :direction, :container_type, :size, :tare, :weight_client,
            :state, :cargo, :seals, :accept_date, :accept_time,
            :in_id, :in_transport, :in_number, :in_driver, :status, NOW(), NOW()
        )
        ON CONFLICT (container_number) DO UPDATE SET
            terminal = EXCLUDED.terminal,
            client = EXCLUDED.client,
            inn = EXCLUDED.inn,
            short_name = EXCLUDED.short_name,
            stock = EXCLUDED.stock,
            customs_mode = EXCLUDED.customs_mode,
            direction = EXCLUDED.direction,
            container_type = EXCLUDED.container_type,
            size = EXCLUDED.size,
            tare = EXCLUDED.tare,
            weight_client = EXCLUDED.weight_client,
            state = EXCLUDED.state,
            cargo = EXCLUDED.cargo,
            seals = EXCLUDED.seals,
            accept_date = EXCLUDED.accept_date,
            accept_time = EXCLUDED.accept_time,
            in_id = EXCLUDED.in_id,
            in_transport = EXCLUDED.in_transport,
            in_number = EXCLUDED.in_number,
            in_driver = EXCLUDED.in_driver,
            status = EXCLUDED.status,
            updated_at = NOW();
    """)
    
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        await session.execute(stmt, batch)
        await session.commit() # Коммитим пачками
    
    logger.info(f"💾 [DB] Upsert завершен для {len(rows)} записей (Arrival).")

async def _bulk_update_dispatch(session: AsyncSession, rows: List[dict]):
    """Выполняет массовый UPDATE для отгрузки."""
    if not rows: return

    stmt = text("""
        UPDATE terminal_containers
        SET 
            status = :status,
            dispatch_date = :dispatch_date,
            dispatch_time = :dispatch_time,
            out_id = :out_id,
            out_transport = :out_transport,
            out_number = :out_number,
            out_driver = :out_driver,
            updated_at = :updated_at
        WHERE container_number = :container_number
    """)
    
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        await session.execute(stmt, batch)
        await session.commit()
        
    logger.info(f"🚚 [DB] Update завершен для {len(rows)} записей (Dispatch).")


# =========================================================================
# 3. ЛОГИКА АДМИНСКОГО ИМПОРТА (ФАЙЛЫ ПОЕЗДОВ) - ВОССТАНОВЛЕНО
# =========================================================================

async def _collect_containers_from_excel(file_path: str) -> Dict[str, str]:
    """
    Читает Excel файл поезда (KXX-YYY) и возвращает мапу {Контейнер: Клиент}.
    Используется в админке для привязки поезда.
    """
    xl = pd.ExcelFile(file_path)
    container_client_map: Dict[str, str] = {}

    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet)
            # Очистка заголовков
            df.columns = [str(c).strip() for c in df.columns]

            # Ищем колонку контейнера
            col_container = find_container_column(df)
            
            # Колонка клиента (предполагаем индекс 11 - столбец L)
            col_client = None
            if len(df.columns) > CLIENT_COLUMN_INDEX:
                col_client = df.columns[CLIENT_COLUMN_INDEX]

            if not col_container:
                logger.warning(f"[Train Import] На листе '{sheet}' не найдена колонка контейнеров.")
                continue

            for _, row in df.iterrows():
                cn = normalize_container(row.get(col_container))
                
                cl_val = None
                if col_client:
                    cl_val = clean_string_value(row.get(col_client))
                
                if cn:
                    # Если клиент не найден, ставим пустую строку или дефолт
                    container_client_map[cn] = cl_val if cl_val else ""
                    
        except Exception as e:
            logger.error(f"[Train Import] Ошибка чтения листа '{sheet}': {e}")

    return container_client_map

async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Функция для админки. Привязывает контейнеры к поезду и клиенту.
    """
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(f"Не удалось извлечь код поезда из имени файла: {os.path.basename(src_file_path)}")

    container_map = await _collect_containers_from_excel(src_file_path)
    total_found = len(container_map)

    if total_found == 0:
        logger.warning(f"[Train Import] Контейнеры не найдены в файле {src_file_path}")
        return 0, 0, train_code

    updated_count = 0
    
    async with SessionLocal() as session:
        async with session.begin():
            for cn, client_name in container_map.items():
                # Обновляем поле train и client у существующего контейнера
                stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == cn
                ).values(
                    train=train_code,
                    client=client_name
                )
                res = await session.execute(stmt)
                updated_count += res.rowcount
    
    logger.info(f"✅ [Train Import] Поезд {train_code}: Привязано {updated_count} контейнеров.")
    return updated_count, total_found, train_code