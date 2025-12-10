# services/terminal_importer.py
from __future__ import annotations

import asyncio
import os
import re
from typing import List, Tuple, Optional, Dict, Any
import pandas as pd
from sqlalchemy import select, update, insert, text
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

# --- КОНСТАНТЫ IMAP ---
SUBJECT_FILTER_TERMINAL = r'executive\s*summary' 
SENDER_FILTER_TERMINAL = 'aterminal@effex.ru' 
FILENAME_PATTERN_TERMINAL = r'A-Terminal.*\.(xlsx|xls|csv)$'

# --- ПАТТЕРНЫ ЛИСТОВ (для Excel) ---
# Если файл многостраничный, ищем эти листы. Если CSV или один лист - не используется.
SHEET_PATTERN_ARRIVAL = r'(arrival|прибытие|принят|поступление)'
SHEET_PATTERN_DISPATCH = r'(dispatch|отправка|отправлен|отгрузка)'

# ==========================================
# === КАРТА КОЛОНОК (Source Header -> DB Field) ===
# ==========================================

# 1. Идентификация
COL_CONTAINER = ['Контейнер', 'Container']

# 2. Общие данные (Arrival Sheet / Левая часть таблицы)
MAPPING_ARRIVAL = {
    'terminal': ['Терминал', 'Terminal'],
    'zone': ['Зона', 'Zone'],
    'client': ['Клиент', 'Client'],
    'inn': ['ИНН', 'INN'],
    'short_name': ['Краткое наименование', 'Short Name'],
    'stock': ['Сток', 'Stock'],
    'customs_mode': ['Таможенный режим', 'Customs'],
    'direction': ['Направление', 'Direction'],
    'container_type': ['Тип', 'Type'],
    'size': ['Размер', 'Size'],
    'payload': ['Грузоподъёмность', 'Payload'],
    'tare': ['Тара', 'Tare'],
    'manufacture_year': ['Год изготовления', 'Year'],
    'weight_client': ['Брутто клиента', 'Client Gross'],
    'weight_terminal': ['Брутто терминала', 'Terminal Gross'],
    'state': ['Состояние', 'State'],
    'cargo': ['Груз', 'Cargo'],
    'temperature': ['Температура', 'Temp'],
    'seals': ['Пломбы', 'Seals'],
    
    # Вход (Левые колонки)
    'in_id': ['Id', 'ID'], 
    'in_transport': ['Транспорт', 'Transport'],
    'in_number': ['Номер вагона | Номер тягача', 'Transport No'],
    'in_driver': ['Станция | Водитель', 'Station/Driver']
}
COL_DATE_IN = ['Принят', 'Date In'] 

# 3. Данные отправки (Правая часть таблицы)
# В CSV колонки дублируются. Pandas добавляет суффикс .1 ко вторым экземплярам.
# Мы ищем именно эти суффиксы для блока отправки.
MAPPING_DISPATCH = {
    'order_number': ['Номер заказа', 'Order No'],
    
    # Правые колонки (с суффиксом .1 или просто дубли в сыром виде)
    'out_id': ['Id.1', 'ID.1', 'Id_1'], 
    'out_transport': ['Транспорт.1', 'Transport.1', 'Транспорт_1'],
    'out_number': ['Номер вагона | Номер тягача.1', 'Transport No.1'],
    'out_driver': ['Станция | Водитель.1', 'Station/Driver.1'],
    
    'release': ['Релиз', 'Release'],
    'carrier': ['Перевозчик', 'Carrier'],
    'manager': ['Менеджер', 'Manager'],
    'comment': ['Примечание', 'Comment']
}
COL_DATE_OUT = ['Отправлен', 'Date Out'] 


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    tz = ZoneInfo("Asia/Vladivostok")
    target_date = datetime.now(tz) - timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")

def normalize_container(value) -> str | None:
    if pd.isna(value) or value is None: return None
    s = str(value).strip().upper()
    if s.endswith('.0'): s = s[:-2]
    # Оставляем только латиницу и цифры
    s = re.sub(r'[^A-Z0-9]', '', s)
    if len(s) < 4: return None
    return s

def normalize_client_name(value) -> str | None:
    if pd.isna(value) or value is None: return None
    s = str(value).strip()
    return s if s else None

def clean_value(val):
    if pd.isna(val) or val is None: return None
    if isinstance(val, str): return val.strip()
    return val

def find_col(df: pd.DataFrame, candidates: List[str]) -> str | None:
    """Ищет колонку в DataFrame, игнорируя регистр."""
    df_cols_lower = {str(c).strip().lower(): str(c) for c in df.columns}
    for cand in candidates:
        cand_lower = cand.lower()
        
        # 1. Точное совпадение
        if cand_lower in df_cols_lower:
            return df_cols_lower[cand_lower]
            
        # 2. Совпадение с суффиксом .1 (для дубликатов)
        if f"{cand_lower}.1" in df_cols_lower:
             return df_cols_lower[f"{cand_lower}.1"]
             
    return None

def parse_datetime(val) -> Tuple[Optional[date], Optional[time]]:
    """Пытается распарсить дату/время из любого формата."""
    if pd.isna(val) or val is None or str(val).strip() == '': return None, None
    try:
        # Если pandas уже распознал как datetime
        if isinstance(val, datetime): return val.date(), val.time()
        
        val_str = str(val).strip()
        # Пробуем разные форматы строк
        for fmt in ['%Y-%m-%d %H:%M:%S', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M', '%Y-%m-%d', '%d.%m.%Y']:
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt.date(), dt.time()
            except ValueError: pass
            
        # Fallback: pandas to_datetime
        dt = pd.to_datetime(val, dayfirst=True)
        return dt.date(), dt.time()
    except: return None, None

def extract_train_from_string(text: str) -> str | None:
    """Ищет номер поезда (К25-103) в строке."""
    if not isinstance(text, str): return None
    # Ищем К/K + цифры. Игнорируем регистр.
    match = re.search(r'([КK]\s*\d{2}[-–—\s]?\d{3})', text, re.IGNORECASE)
    if match:
        # Нормализуем: Латинскую K меняем на Русскую, убираем пробелы
        raw = match.group(1).upper().replace('K', 'К').replace(' ', '')
        # Добавляем дефис если нет (К25103 -> К25-103)
        if '-' not in raw and len(raw) >= 5: 
            raw = raw[:3] + '-' + raw[3:]
        return raw
    return None

# --- ГЛАВНАЯ ЛОГИКА ОБРАБОТКИ ---

async def _process_full_table(session, df: pd.DataFrame, stats: Dict[str, int]):
    """
    Обрабатывает DataFrame, содержащий ВСЕ колонки (и Arrival, и Dispatch).
    """
    # 1. Ищем главную колонку - Контейнер
    col_cont = find_col(df, COL_CONTAINER)
    if not col_cont:
        logger.warning(f"❌ В файле не найдена колонка 'Контейнер'. Заголовки: {list(df.columns)}")
        return

    # 2. Определяем реальные имена колонок для ARRIVAL
    map_arr_actual = {}
    for db_field, candidates in MAPPING_ARRIVAL.items():
        found = find_col(df, candidates)
        if found: map_arr_actual[db_field] = found
    col_date_in = find_col(df, COL_DATE_IN)

    # 3. Определяем реальные имена колонок для DISPATCH
    map_disp_actual = {}
    for db_field, candidates in MAPPING_DISPATCH.items():
        found = find_col(df, candidates)
        if found: map_disp_actual[db_field] = found
    col_date_out = find_col(df, COL_DATE_OUT)

    # Превращаем в список словарей для итерации
    records = df.to_dict('records')
    
    logger.info(f"Найдено строк данных: {len(records)}")

    for row in records:
        container_no = normalize_container(row.get(col_cont))
        if not container_no: continue

        data = {}

        # --- СБОР ДАННЫХ ПРИБЫТИЯ ---
        for db_field, excel_col in map_arr_actual.items():
            val = clean_value(row.get(excel_col))
            if val is not None: data[db_field] = val
            
        if col_date_in:
            d, t = parse_datetime(row.get(col_date_in))
            if d: 
                data['accept_date'] = d
                data['accept_time'] = t

        # --- СБОР ДАННЫХ ОТПРАВКИ ---
        for db_field, excel_col in map_disp_actual.items():
            val = clean_value(row.get(excel_col))
            if val is not None: data[db_field] = val
            
        # Логика даты отправки и статуса
        if col_date_out:
            d_out, t_out = parse_datetime(row.get(col_date_out))
            if d_out:
                data['dispatch_date'] = d_out
                data['dispatch_time'] = t_out
                data['status'] = 'ОТГРУЖЕН'
            else:
                data['status'] = 'ПРИНЯТ' # Если даты нет, значит еще на терминале
        else:
            data['status'] = 'ПРИНЯТ'

        # Извлекаем поезд из номера заказа, если он есть
        if 'order_number' in data and data['order_number']:
            train_val = extract_train_from_string(str(data['order_number']))
            if train_val: 
                data['train'] = train_val
            # Fallback: иногда поезд пишут в Примечании
            elif 'comment' in data and data['comment']:
                 train_val_comment = extract_train_from_string(str(data['comment']))
                 if train_val_comment: data['train'] = train_val_comment

        # --- СОХРАНЕНИЕ В БД (Upsert) ---
        
        # 1. Пробуем обновить (UPDATE), если контейнер уже есть
        stmt_update = update(TerminalContainer).where(
            TerminalContainer.container_number == container_no
        ).values(**data)
        
        res = await session.execute(stmt_update)
        
        if res.rowcount > 0:
            stats['updated'] += 1
        else:
            # 2. Если не нашли, создаем новый (INSERT)
            data['container_number'] = container_no
            try:
                await session.execute(insert(TerminalContainer).values(**data))
                stats['added'] += 1
            except SQLAlchemyError as e:
                # В случае гонки или дубля
                await session.rollback()
                continue

async def process_terminal_report_file(filepath: str) -> Dict[str, int]:
    logger.info(f"[Import] Запуск обработки файла: {os.path.basename(filepath)}")
    stats = {'updated': 0, 'added': 0}
    
    try:
        # Читаем файл. Поддержка CSV и Excel.
        if filepath.lower().endswith('.csv'):
            # Читаем CSV (авто-детект разделителя, или пробуем стандартные)
            try:
                df = pd.read_csv(filepath, sep=None, engine='python')
            except:
                df = pd.read_csv(filepath, sep=';') # Пробуем ; если авто не сработал
        else:
            # Читаем Excel
            xl = pd.ExcelFile(filepath)
            # Берем первый лист (обычно он и нужен)
            df = pd.read_excel(xl, sheet_name=0)

        async with SessionLocal() as session:
            async with session.begin():
                logger.info(f"Таблица загружена ({len(df)} строк). Начинаю импорт в БД...")
                await _process_full_table(session, df, stats)

        logger.info(f"✅ Импорт завершен. Добавлено: {stats['added']}, Обновлено: {stats['updated']}")
        return stats

    except Exception as e:
        logger.error(f"❌ Ошибка импорта: {e}", exc_info=True)
        return stats

# --- Совместимость с Scheduler ---

async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    """
    Функция для планировщика. Скачивает файл с почты и запускает процессинг.
    """
    logger.info("[Scheduler] Поиск отчета терминала (IMAP)...")
    
    # Ищем письмо с темой, содержащей 'Executive summary'
    fp = await asyncio.to_thread(
        imap_service.download_latest_attachment, 
        fr"{SUBJECT_FILTER_TERMINAL}", 
        SENDER_FILTER_TERMINAL, 
        FILENAME_PATTERN_TERMINAL
    )
    
    if not fp: 
        logger.info("Новых отчетов на почте не найдено.")
        return {'file_name': 'Not found'}
    
    try:
        stats = await process_terminal_report_file(fp)
        stats['file_name'] = os.path.basename(fp)
        return stats
    finally:
        if fp and os.path.exists(fp): os.remove(fp)

# Заглушки для обратной совместимости (если где-то вызываются)
async def import_train_from_excel(src): return 0,0,""
async def _collect_containers_from_excel(src): return {}