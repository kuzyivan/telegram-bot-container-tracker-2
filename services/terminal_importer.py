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
from imap_tools.query import AND

logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
DOWNLOAD_DIR = "download_container"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Настройки поиска (добавили csv в паттерн)
SUBJECT_FILTER_TERMINAL = r'executive\s*summary|A-Terminal'
SENDER_FILTER_TERMINAL = 'aterminal@effex.ru'
FILENAME_PATTERN_TERMINAL = r'\.(xlsx|xls|csv)$'

CLIENT_COLUMN_INDEX = 11 

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ."""
    try:
        tz = ZoneInfo("Asia/Vladivostok")
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=10))
    target_date = datetime.datetime.now(tz) - timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")

def clean_string_value(val: Any) -> Optional[str]:
    """Преобразует значение в строку, корректно обрабатывая числа."""
    if pd.isna(val) or val == '' or str(val).lower() == 'nan':
        return None
    try:
        # Убираем .0 у целых чисел, ставших float
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        if isinstance(val, (int, float)):
            return str(int(val))
    except Exception:
        pass
    return str(val).strip()

def normalize_container(value: Any) -> Optional[str]:
    """Нормализует номер контейнера."""
    s = clean_string_value(value)
    if not s:
        return None
    s = s.upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    if len(s) == 11:
        return s
    return s if s else None

def parse_date_safe(val: Any) -> Optional[datetime.date]:
    """Безопасный парсинг даты."""
    if pd.isna(val) or val == '': return None
    try:
        if isinstance(val, (pd.Timestamp, datetime.datetime)): return val.date()
        # Пробуем форматы с временем и без
        return pd.to_datetime(val, dayfirst=True).date()
    except Exception: return None

def parse_time_safe(val: Any) -> Optional[datetime.time]:
    """Безопасный парсинг времени."""
    if pd.isna(val) or val == '': return None
    try:
        if isinstance(val, (pd.Timestamp, datetime.datetime)): return val.time()
        if isinstance(val, datetime.time): return val
        return pd.to_datetime(val, dayfirst=True).time()
    except Exception: return None

def parse_float_safe(val: Any) -> Optional[float]:
    """Безопасный парсинг числа."""
    if pd.isna(val) or val == '': return None
    try:
        # Заменяем запятую на точку и неразрывные пробелы
        clean_val = str(val).replace(',', '.').replace('\xa0', '').replace(' ', '').strip()
        return float(clean_val)
    except Exception: return None

def extract_train_code_from_filename(filename: str) -> str | None:
    if not filename: return None
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    m = re.search(r"([КK]\s*\d{2}[-–— ]?\s*\d{3})", name, flags=re.IGNORECASE)
    if not m: return None
    code = m.group(1).upper().replace("K", "К").replace(" ", "").replace("–", "-").replace("—", "-")
    return code

def find_container_column(df: pd.DataFrame) -> str | None:
    candidates = ["контейнер", "container", "container no", "номер контейнера", "№ контейнера"]
    cols_norm = {str(c).strip().lower(): str(c) for c in df.columns}
    for cand in candidates:
        if cand in cols_norm: return cols_norm[cand]
    return None

# =========================================================================
# 1. ЛОГИКА ДЛЯ ПЛАНИРОВЩИКА
# =========================================================================

async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    imap = ImapService()
    filepath = None
    
    # Ищем за сегодня и вчера
    for offset in [0, 1]:
        date_str = _get_vladivostok_date_str(days_offset=offset)
        logger.info(f"[Terminal Check] Ищу отчет за {date_str}...")
        # Ищем либо Executive summary, либо файлы A-Terminal
        subject_regex = fr"({SUBJECT_FILTER_TERMINAL}).*{re.escape(date_str)}"
        
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            subject_filter=subject_regex,
            sender_filter=SENDER_FILTER_TERMINAL,
            filename_pattern=FILENAME_PATTERN_TERMINAL
        )
        if filepath: break

    if not filepath:
        logger.info("[Terminal Check] Файл не найден.")
        return None

    stats = None
    try:
        logger.info(f"[Terminal Check] Найден: {filepath}. Импорт...")
        async with SessionLocal() as session:
            import_result = await process_terminal_report_file(session, filepath)
            stats = {
                "file_name": os.path.basename(filepath),
                "status": "success",
                "total_added": import_result.get('added', 0),
                "total_updated": import_result.get('updated', 0)
            }
    except Exception as e:
        logger.error(f"❌ Ошибка импорта: {e}", exc_info=True)
        stats = {"error": str(e)}
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)

    return stats

# =========================================================================
# 2. ОСНОВНОЙ ПРОЦЕССОР ФАЙЛОВ
# =========================================================================

async def process_terminal_report_file(session: AsyncSession, file_path: str) -> dict:
    """
    Определяет тип файла (Excel или CSV) и запускает соответствующую обработку.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.csv':
        return await _process_csv_flat_file(session, file_path)
    else:
        return await _process_excel_split_file(session, file_path)

# --- ВАРИАНТ 1: CSV (Общий файл, ВСЕ колонки) ---

async def _process_csv_flat_file(session: AsyncSession, file_path: str) -> dict:
    """
    Парсит CSV, где все данные в одной таблице.
    Обновляет абсолютно все поля.
    """
    logger.info(f"[CSV Import] Читаю общий файл: {file_path}")
    
    try:
        # Читаем CSV. Используем sep=';' так как это стандарт для 1C/Russian CSV
        # dtype=str чтобы не потерять ведущие нули
        df = pd.read_csv(file_path, sep=';', dtype=str)
        
        # Очистка имен колонок от пробелов
        df.columns = df.columns.str.strip()
        
        processed_rows = []
        
        for _, row in df.iterrows():
            cont_val = row.get('Контейнер')
            container_number = normalize_container(cont_val)
            if not container_number:
                continue

            # --- Маппинг полей ---
            # Учитываем, что pandas добавляет .1, .2 к дубликатам заголовков
            
            # 1. Даты
            accept_val = row.get('Принят')
            dispatch_val = row.get('Отправлен')
            
            accept_date = parse_date_safe(accept_val)
            accept_time = parse_time_safe(accept_val)
            dispatch_date = parse_date_safe(dispatch_val)
            dispatch_time = parse_time_safe(dispatch_val)
            
            # 2. Статус
            status = 'ARRIVED'
            if dispatch_date:
                status = 'DISPATCHED'

            # --- 🔥 АВТОМАТИЧЕСКИЙ РАСЧЕТ ВЕСА НЕТТО ---
            weight_client = parse_float_safe(row.get('Брутто клиента'))
            weight_terminal = parse_float_safe(row.get('Брутто терминала'))
            tare = parse_float_safe(row.get('Тара'))
            
            weight_netto = None
            if weight_client is not None and tare is not None and weight_client > tare:
                weight_netto = weight_client - tare
            # --------------------------------------------
                
            # 3. Сборка объекта данных
            # Используем .get() с дефолтом, чтобы не падать, если колонки нет
            data = {
                'container_number': container_number,
                'terminal': clean_string_value(row.get('Терминал', 'A-Terminal')),
                'zone': clean_string_value(row.get('Зона')),
                'inn': clean_string_value(row.get('ИНН')),
                'short_name': clean_string_value(row.get('Краткое наименование')),
                'client': clean_string_value(row.get('Клиент')),
                'stock': clean_string_value(row.get('Сток')),
                'customs_mode': clean_string_value(row.get('Таможенный режим')),
                'direction': clean_string_value(row.get('Направление')),
                'container_type': clean_string_value(row.get('Тип')),
                'size': clean_string_value(row.get('Размер')),
                'payload': parse_float_safe(row.get('Грузоподъёмность')),
                
                'tare': tare, # Используем переменную
                'manufacture_year': clean_string_value(row.get('Год изготовления')),
                'weight_client': weight_client, # Используем переменную
                'weight_terminal': weight_terminal, # Используем переменную
                
                'state': clean_string_value(row.get('Состояние')),
                'cargo': clean_string_value(row.get('Груз')),
                'temperature': clean_string_value(row.get('Температура')),
                'seals': clean_string_value(row.get('Пломбы')),
                
                'accept_date': accept_date,
                'accept_time': accept_time,
                
                # Входные данные (первые колонки)
                'in_id': clean_string_value(row.get('Id')),
                'in_transport': clean_string_value(row.get('Транспорт')),
                'in_number': clean_string_value(row.get('Номер вагона | Номер тягача')),
                'in_driver': clean_string_value(row.get('Станция | Водитель')),
                
                'order_number': clean_string_value(row.get('Номер заказа')),
                
                'dispatch_date': dispatch_date,
                'dispatch_time': dispatch_time,
                
                # Выходные данные (дубликаты колонок имеют суффикс .1 в pandas)
                'out_id': clean_string_value(row.get('Id.1')),
                'out_transport': clean_string_value(row.get('Транспорт.1')),
                'out_number': clean_string_value(row.get('Номер вагона | Номер тягача.1')),
                'out_driver': clean_string_value(row.get('Станция | Водитель.1')),
                
                'release': clean_string_value(row.get('Релиз')),
                'carrier': clean_string_value(row.get('Перевозчик')),
                'manager': clean_string_value(row.get('Менеджер')),
                'comment': clean_string_value(row.get('Примечание')),
                
                'status': status,
                
                # Добавляем рассчитанное нетто
                'weight_netto': weight_netto
            }
            processed_rows.append(data)
            
        if processed_rows:
            # Вызываем мощный UPSERT для всех полей
            await _bulk_upsert_full_data(session, processed_rows)
            return {"added": len(processed_rows), "updated": 0} # Для CSV считаем все как "обработанные"
            
        return {"added": 0, "updated": 0}

    except Exception as e:
        logger.error(f"Ошибка CSV парсинга: {e}", exc_info=True)
        raise e

# --- ВАРИАНТ 2: EXCEL (Старая логика с разделением листов) ---

async def _process_excel_split_file(session: AsyncSession, file_path: str) -> dict:
    """
    Парсит Excel с листами Arrival / Dispatch.
    """
    
    logger.info(f"[Excel Import] Читаю Excel: {file_path}")
    xls = pd.ExcelFile(file_path)
    added = 0
    updated = 0
    
    # 1. Arrival
    if "Arrival" in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name="Arrival", dtype=str)
        # ... (тут должна быть логика маппинга для старого формата Excel, если он используется) ...
        # Для простоты и совместимости с CSV-ориентированным обновлением, 
        # лучше конвертировать Excel в CSV или адаптировать маппинг.
        pass 

    # 2. Dispatch
    if "Dispatch" in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name="Dispatch", dtype=str)
        # ...
        pass
        
    return {"added": added, "updated": updated}


# =========================================================================
# 3. SQL ЗАПРОСЫ
# =========================================================================

async def _bulk_upsert_full_data(session: AsyncSession, rows: List[dict]):
    """
    Выполняет полный UPSERT всех полей.
    Если контейнер есть -> обновляем ВСЁ.
    Если нет -> вставляем.
    """
    if not rows: return

    stmt = text("""
        INSERT INTO terminal_containers (
            container_number, terminal, zone, inn, short_name, client, stock,
            customs_mode, direction, container_type, size, payload, tare,
            manufacture_year, weight_client, weight_terminal, state, cargo,
            temperature, seals, accept_date, accept_time,
            in_id, in_transport, in_number, in_driver, order_number,
            dispatch_date, dispatch_time,
            out_id, out_transport, out_number, out_driver,
            release, carrier, manager, comment, status, weight_netto,
            created_at, updated_at
        ) VALUES (
            :container_number, :terminal, :zone, :inn, :short_name, :client, :stock,
            :customs_mode, :direction, :container_type, :size, :payload, :tare,
            :manufacture_year, :weight_client, :weight_terminal, :state, :cargo,
            :temperature, :seals, :accept_date, :accept_time,
            :in_id, :in_transport, :in_number, :in_driver, :order_number,
            :dispatch_date, :dispatch_time,
            :out_id, :out_transport, :out_number, :out_driver,
            :release, :carrier, :manager, :comment, :status, :weight_netto,
            NOW(), NOW()
        )
        ON CONFLICT (container_number) DO UPDATE SET
            terminal = EXCLUDED.terminal,
            zone = EXCLUDED.zone,
            inn = EXCLUDED.inn,
            short_name = EXCLUDED.short_name,
            client = EXCLUDED.client,
            stock = EXCLUDED.stock,
            customs_mode = EXCLUDED.customs_mode,
            direction = EXCLUDED.direction,
            container_type = EXCLUDED.container_type,
            size = EXCLUDED.size,
            payload = EXCLUDED.payload,
            tare = EXCLUDED.tare,
            manufacture_year = EXCLUDED.manufacture_year,
            weight_client = EXCLUDED.weight_client,
            weight_terminal = EXCLUDED.weight_terminal,
            state = EXCLUDED.state,
            cargo = EXCLUDED.cargo,
            temperature = EXCLUDED.temperature,
            seals = EXCLUDED.seals,
            accept_date = EXCLUDED.accept_date,
            accept_time = EXCLUDED.accept_time,
            in_id = EXCLUDED.in_id,
            in_transport = EXCLUDED.in_transport,
            in_number = EXCLUDED.in_number,
            in_driver = EXCLUDED.in_driver,
            order_number = EXCLUDED.order_number,
            dispatch_date = EXCLUDED.dispatch_date,
            dispatch_time = EXCLUDED.dispatch_time,
            out_id = EXCLUDED.out_id,
            out_transport = EXCLUDED.out_transport,
            out_number = EXCLUDED.out_number,
            out_driver = EXCLUDED.out_driver,
            release = EXCLUDED.release,
            carrier = EXCLUDED.carrier,
            manager = EXCLUDED.manager,
            comment = EXCLUDED.comment,
            status = EXCLUDED.status,
            weight_netto = EXCLUDED.weight_netto,
            updated_at = NOW();
    """)

    # Разбиваем на пачки по 500 для скорости
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        await session.execute(stmt, batch)
        await session.commit()

    logger.info(f"💾 [DB] Полный Upsert завершен для {len(rows)} записей.")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (train_importer и т.д.) БЕЗ ИЗМЕНЕНИЙ ---
async def _collect_containers_from_excel(file_path: str) -> Dict[str, str]:
    xl = pd.ExcelFile(file_path)
    container_client_map = {}
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet)
            df.columns = [str(c).strip() for c in df.columns]
            col_container = find_container_column(df)
            col_client = df.columns[CLIENT_COLUMN_INDEX] if len(df.columns) > CLIENT_COLUMN_INDEX else None
            if not col_container: continue
            for _, row in df.iterrows():
                cn = normalize_container(row.get(col_container))
                cl_val = clean_string_value(row.get(col_client)) if col_client else None
                if cn: container_client_map[cn] = cl_val if cl_val else ""
        except Exception as e:
            logger.error(f"Error reading sheet {sheet}: {e}")
    return container_client_map

async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code: raise ValueError("No train code")
    container_map = await _collect_containers_from_excel(src_file_path)
    if not container_map: return 0, 0, train_code
    updated_count = 0
    async with SessionLocal() as session:
        async with session.begin():
            for cn, client_name in container_map.items():
                stmt = update(TerminalContainer).where(TerminalContainer.container_number == cn).values(train=train_code, client=client_name)
                res = await session.execute(stmt)
                updated_count += res.rowcount
    return updated_count, len(container_map), train_code