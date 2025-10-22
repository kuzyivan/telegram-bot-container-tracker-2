# services/terminal_importer.py
from __future__ import annotations

import asyncio
import os
import re
from typing import List, Tuple, Optional, Dict, Any
import pandas as pd
from sqlalchemy import select, update, insert
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, date, time

from logger import get_logger
from model.terminal_container import TerminalContainer
from db import SessionLocal 
from services.imap_service import ImapService 

logger = get_logger(__name__)
imap_service = ImapService() 
DOWNLOAD_DIR_TERMINAL = "downloads/terminal" 

# ✅ ФИНАЛЬНЫЙ СЛОВАРЬ СОПОСТАВЛЕНИЯ (на основе вашего списка столбцов)
# Ключи - точные названия из Excel-файла
TERMINAL_COLUMN_MAPPING = {
    'Контейнер': 'container_number',
    'Клиент': 'client',
    'Состояние': 'status',     # Используем "Состояние" вместо "Статус"
    'Принят': 'accept_datetime', # Временный ключ, т.к. в БД два поля (date и time)
}

# --- Вспомогательные функции (остаются прежними) ---

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
    """Нормализует номер контейнера, обрабатывая float."""
    if pd.isna(value) or value is None: return None
    s = str(value).strip().upper()
    if s.endswith('.0'): s = s[:-2]
    return s if s else None


def find_container_column(df: pd.DataFrame) -> str | None:
    """Пытаемся найти колонку с номерами контейнеров."""
    # ✅ Обновляем поиск, чтобы найти 'Контейнер'
    candidates = ["контейнер", "container", "container no", "container no.", 
                  "номер контейнера", "№ контейнера", "номенклатура"]
    
    cols_norm = {str(c).strip().lower(): c for c in df.columns}
    
    for cand in candidates:
        if cand in cols_norm: return cols_norm[cand]
    
    for col in df.columns:
        name = str(col).strip().lower()
        if name.startswith("contain") or "контейнер" in name: return col
            
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
        df = pd.read_excel(xl, sheet_name=target_sheet_name, header=0) 
        
        # 3. Очистка и обработка колонок
        # ✅ ИСПРАВЛЕНИЕ: Мы больше не заменяем пробелы, только убираем лишние
        df.columns = [c.strip() for c in df.columns]
        df = df.dropna(how='all')
        
        # 4. Выбираем только нужные столбцы
        required_cols = list(TERMINAL_COLUMN_MAPPING.keys())
        existing_required_cols = [col for col in required_cols if col in df.columns]
        
        # Проверяем, что нашли 'Контейнер'
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
                # ✅ Получаем по ключу 'Контейнер'
                container_number_raw = record.get('Контейнер') 
                if not container_number_raw or pd.isna(container_number_raw):
                    continue

                container_number = str(container_number_raw).removesuffix('.0')

                cleaned_record_for_db = {}
                # key_excel - это "Контейнер", "Клиент" и т.д.
                for key_excel, value in record.items():
                    # Проверяем, что ключ есть в маппинге и значение не пустое
                    if key_excel in TERMINAL_COLUMN_MAPPING and pd.notna(value):
                        
                        mapped_key_db = TERMINAL_COLUMN_MAPPING[key_excel]
                        
                        # ✅ ОСОБАЯ ОБРАБОТКА ДАТЫ/ВРЕМЕНИ
                        if mapped_key_db == 'accept_datetime':
                            if isinstance(value, datetime):
                                cleaned_record_for_db['accept_date'] = value.date()
                                cleaned_record_for_db['accept_time'] = value.time()
                            elif isinstance(value, date):
                                cleaned_record_for_db['accept_date'] = value
                            elif isinstance(value, time):
                                cleaned_record_for_db['accept_time'] = value
                        
                        # Пропускаем 'container_number', он пойдет отдельно
                        elif mapped_key_db == 'container_number':
                            continue
                        
                        else:
                            cleaned_record_for_db[mapped_key_db] = value
                
                # Пропускаем, если в словаре нет ничего
                if not cleaned_record_for_db: 
                    continue 
                
                # 1. Попытка обновить (UPDATE)
                # cleaned_record_for_db теперь содержит {'client': '...', 'status': '...', 'accept_date': ...}
                update_stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == container_number
                ).values(**cleaned_record_for_db)
                
                result = await session.execute(update_stmt)

                if result.rowcount > 0:
                    updated_count += 1
                else:
                    # 2. Если не обновили, вставляем новую запись (INSERT)
                    cleaned_record_for_db['container_number'] = container_number 
                    insert_stmt = insert(TerminalContainer).values(**cleaned_record_for_db)
                    try:
                        await session.execute(insert_stmt)
                        added_count += 1
                    except SQLAlchemyError as e:
                        logger.warning(f"Ошибка INSERT для {container_number} (возможно, уже существует): {e}")
                        pass # Просто пропускаем
            
        logger.info(f"✅ [Terminal Report] Обновление завершено. Добавлено: {added_count}, Обновлено: {updated_count}.")

    return {'updated': updated_count, 'added': added_count}


# --- Функции, оставшиеся в файле для целостности ---

async def _collect_containers_from_excel(file_path: str) -> Dict[str, str]:
    """
    Читает Excel (для файла поезда) и возвращает словарь {container_number: client_name}.
    """
    xl = pd.ExcelFile(file_path)
    container_client_map: Dict[str, str] = {}
    
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet) 
            # ✅ ИСПРАВЛЕНИЕ: ищем 'Контейнер'
            df.columns = [str(c).strip() for c in df.columns]
            
            # Ищем 'Контейнер' или его варианты
            container_col_header = find_container_column(df)
            
            CLIENT_COLUMN_INDEX = 11 # L-колонка для клиента
            if CLIENT_COLUMN_INDEX >= len(df.columns): 
                logger.warning(f"[train_importer] На листе '{sheet}' нет колонки {CLIENT_COLUMN_INDEX} (Клиент). Пропускаю.")
                continue
                
            client_col_header = df.columns[CLIENT_COLUMN_INDEX]

            if not container_col_header: 
                logger.warning(f"[train_importer] На листе '{sheet}' не найдена колонка контейнеров. Пропускаю.")
                continue

            for _, row in df.iterrows():
                cn = normalize_container(row.get(container_col_header))
                client = normalize_client_name(row.get(client_col_header))
                
                if cn and client:
                    container_client_map[cn] = client
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
        logger.warning(f"[train_importer] В файле поезда нет распознанных контейнеров: {os.path.basename(src_file_path)}")
        return 0, 0, train_code

    updated = 0
    try:
        async with SessionLocal() as session:
            
            for cn, client_name in container_client_map.items():
                
                update_stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == cn
                ).values(
                    train=train_code,
                    client=client_name
                )
                
                result = await session.execute(update_stmt)
                updated += result.rowcount

            await session.commit()

        logger.info(f"✅ [train_importer] Поезд {train_code}: обновлено {updated} из {total_in_file} (найденных в файле).")
        return updated, total_in_file, train_code

    except SQLAlchemyError as e:
        logger.error(f"[train_importer] Ошибка БД при импорте поезда: {e}", exc_info=True)
        raise
        

async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    """
    Функция для scheduler (ежедневная проверка почты).
    """
    logger.info("[Terminal Import] Проверка почты на наличие отчета терминала...")
    
    # TODO: Раскомментируйте и настройте это, когда будете готовы
    # filepath = await asyncio.to_thread(
    #     imap_service.download_latest_attachment,
    #     subject_filter=r'A-Terminal', # Установите правильный фильтр
    #     sender_filter='sender@example.com', # Установите правильного отправителя
    #     filename_pattern=r'A-Terminal.*\.xlsx$'
    # )
    # if filepath:
    #     try:
    #         stats = await process_terminal_report_file(filepath)
    #         return stats
    #     finally:
    #         if os.path.exists(filepath):
    #             os.remove(filepath)
    
    logger.info("[Terminal Import] Проверка почты (по расписанию) пока отключена.")
    return {'file_name': 'Disabled', 'sheets_processed': 0, 'total_added': 0}