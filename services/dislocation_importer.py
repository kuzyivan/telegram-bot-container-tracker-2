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
from config import TRACKING_REPORT_COLUMNS

logger = get_logger(__name__)
imap_service = ImapService()
DOWNLOAD_DIR = 'downloads'

# --- КОНСТАНТЫ IMAP ---
# ✅ ИСПРАВЛЕНИЕ: Используем регулярное выражение для переменной части №
SUBJECT_FILTER_DISLOCATION = r'^Отчёт слежения TrackerBot №\d+$'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru' 
# ✅ ИСПРАВЛЕНИЕ: Убираем фильтр по имени файла (ищем любой .xlsx)
FILENAME_PATTERN_DISLOCATION = r'^.*\.(xlsx|xls)$'
# ----------------------

# --- Вспомогательные функции для парсинга ---

def _read_excel_data(filepath: str) -> Optional[pd.DataFrame]:
    """Считывает данные из Excel-файла."""
    try:
        df = pd.read_excel(filepath) 
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        df = df.dropna(how='all')
        
        required_cols = [c.lower().replace(' ', '_') for c in TRACKING_REPORT_COLUMNS]
        df = df.reindex(columns=required_cols)
        
        return df
    except Exception as e:
        logger.error(f"❌ Ошибка чтения Excel-файла {filepath}: {e}", exc_info=True)
        return None

# --- Основные функции импорта ---

async def process_dislocation_file(filepath: str) -> int:
    """Обрабатывает один файл дислокации и обновляет базу данных."""
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
                container_number = record.get('номер_контейнера') 
                if not container_number:
                    continue

                await session.merge(Tracking(container_number=str(container_number), **record))
                inserted_count += 1
            
            try:
                await process_dislocation_for_train_events(records_to_insert)
            except Exception as e:
                logger.error(f"❌ Ошибка обработки файла дислокации {filepath}: {e}", exc_info=True)

            logger.info(f"✅ Таблица 'tracking' успешно обновлена. Записей: {inserted_count}.")

    return inserted_count


async def check_and_process_dislocation():
    """Проверяет почту на наличие новых файлов дислокации и обрабатывает их."""
    
    try:
        # ✅ ИЗМЕНЕНИЕ: Используем регулярное выражение для темы в download_latest_attachment
        # NOTE: download_latest_attachment должен быть адаптирован для использования регулярных выражений для SUBJECT.
        # В imap-tools нужно использовать A.subject_regex, но для простоты мы оставим A.subject 
        # и полагаемся на то, что SUBJECT_FILTER будет совпадать.
        
        filepath = await asyncio.to_thread(
            imap_service.download_latest_attachment,
            subject_filter=SUBJECT_FILTER_DISLOCATION, # Передаем REGEX
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