# services/dislocation_importer.py

import asyncio
import os
import re
import pandas as pd
from typing import Optional
from logger import get_logger
from services.imap_service import ImapService
from services.train_event_notifier import process_dislocation_for_train_events
from db import SessionLocal
from models import Tracking
from sqlalchemy import update, insert 
from config import TRACKING_REPORT_COLUMNS
from datetime import datetime

logger = get_logger(__name__)
imap_service = ImapService()
DOWNLOAD_DIR = 'downloads'

# ✅ КРИТИЧЕСКИЙ СЛОВАРЬ СОПОСТАВЛЕНИЯ
COLUMN_MAPPING = {
    'номер_контейнера': 'container_number',
    'станция_отправления': 'from_station',
    'станция_назначения': 'to_station',
    'станция_операции': 'current_station',  
    'операция': 'operation',
    'дата_и_время_операции': 'operation_date',
    'номер_накладной': 'waybill',
    'расстояние_оставшееся': 'km_left',
    'номер_вагона': 'wagon_number',
    'дорога_операции': 'operation_road',
}

# --- КОНСТАНТЫ IMAP ---
SUBJECT_FILTER_DISLOCATION = r'^Отчёт слежения TrackerBot №'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru' 
FILENAME_PATTERN_DISLOCATION = r'^.*\.(xlsx|xls)$'
# ----------------------

# --- Вспомогательные функции для парсинга ---

def _read_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """Считывает данные из Excel-файла, пропуская лишние верхние строки."""
    try:
        # Критическое исправление: Пропускаем 3 строки, не относящиеся к данным.
        df = pd.read_excel(filepath, skiprows=3, header=0) 
        
        # Приводим названия колонок к нижнему регистру и заменяем пробелы
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        
        # Фильтруем пустые строки
        df = df.dropna(how='all')
        
        # Выбираем только нужные колонки, которые есть в нашей модели
        required_cols = list(COLUMN_MAPPING.keys())
        df = df.reindex(columns=required_cols)
        
        return df
    except Exception as e:
        logger.error(f"❌ Ошибка чтения Excel-файла {filepath}: {e}", exc_info=True)
        return None

# --- Основные функции импорта ---

async def process_dislocation_file(filepath: str) -> int:
    """
    Обрабатывает один файл дислокации, используя UPDATE/INSERT 
    для обновления самой свежей записи по container_number.
    """
    logger.info(f"[Dislocation Import] Начало обработки файла: {os.path.basename(filepath)}")
    
    df = await asyncio.to_thread(_read_excel_data, filepath)
    if df is None or df.empty:
        logger.warning(f"[Dislocation Import] Файл {os.path.basename(filepath)} пуст или не содержит данных.")
        return 0

    records_to_insert = df.to_dict('records')
    inserted_count = 0

    async with SessionLocal() as session:
        async with session.begin():
            for record in records_to_insert:
                container_number_raw = record.get('номер_контейнера') 
                
                # 1. Пропускаем, если номер контейнера отсутствует
                if not container_number_raw or pd.isna(container_number_raw):
                    continue

                # ✅ ИСПРАВЛЕНИЕ: Гарантируем, что номер контейнера - строка
                container_number = str(container_number_raw).removesuffix('.0')

                # Очищаем и преобразуем словарь для обновления
                cleaned_record = {}
                for key_ru, value in record.items():
                    if pd.notna(value) and key_ru in COLUMN_MAPPING:
                        
                        mapped_key = COLUMN_MAPPING[key_ru]
                        
                        # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ ТИПА ДАННЫХ: Преобразование в str
                        if mapped_key in ['wagon_number', 'waybill']:
                            # Преобразуем число/float в строку и убираем .0
                            cleaned_record[mapped_key] = str(value).removesuffix('.0')
                        
                        elif isinstance(value, datetime) and value.tzinfo is not None:
                            # Удаляем timezone из datetime
                            cleaned_record[mapped_key] = value.replace(tzinfo=None)
                            
                        else:
                            # Оставляем остальные поля как есть
                            cleaned_record[mapped_key] = value


                # Пропускаем, если нет данных для SET (кроме container_number, который используется в WHERE)
                if not cleaned_record:
                    logger.warning(f"[Dislocation Import] Пропущена строка для {container_number}: нет данных для обновления.")
                    continue 

                # 1. Сначала пытаемся обновить существующую запись
                update_stmt = update(Tracking).where(
                    Tracking.container_number == container_number
                ).values(**cleaned_record) 
                
                result = await session.execute(update_stmt)

                if result.rowcount == 0:
                    # 2. Если не обновили (не нашли), то вставляем новую запись
                    insert_stmt = insert(Tracking).values(container_number=container_number, **cleaned_record)
                    await session.execute(insert_stmt)
                
                inserted_count += 1
            
            # Запускаем обработчик событий поезда (требует актуальных записей Tracking)
            try:
                await process_dislocation_for_train_events(records_to_insert)
            except Exception as e:
                logger.error(f"❌ Ошибка обработки файла дислокации {filepath}: {e}", exc_info=True)

            logger.info(f"✅ Таблица 'tracking' успешно обновлена. Записей: {inserted_count}.")

    return inserted_count


async def check_and_process_dislocation():
    """Проверяет почту на наличие новых файлов дислокации и обрабатывает их."""
    
    try:
        # Передаем REGEX для темы
        filepath = await asyncio.to_thread(
            imap_service.download_latest_attachment,
            subject_filter=SUBJECT_FILTER_DISLOCATION,
            sender_filter=SENDER_FILTER_DISLOCATION,
            filename_pattern=FILENAME_PATTERN_DISLOCATION
        )

        if filepath:
            try:
                await process_dislocation_file(filepath)
            except Exception as e:
                logger.error(f"❌ Ошибка обработки файла дислокации {filepath}: {e}", exc_info=True)
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"[Dislocation Import] Временный файл {os.path.basename(filepath)} удален.")
        else:
            logger.info("📬 [Dislocation] Новых файлов дислокации не найдено.")

    except Exception as e:
        raise e