# utils/send_tracking.py
import os
import pandas as pd
from io import BytesIO
from datetime import datetime
from typing import List, Any
import logging
from pytz import timezone # <-- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ДОБАВЛЕН ИМПОРТ timezone
import uuid # Используется для создания временных файлов

logger = logging.getLogger(__name__)

def create_excel_file(rows: List[List[Any]], columns: List[str]) -> str:
    """Создает временный Excel-файл из списка строк и заголовков."""
    logger.info(f"Создание Excel-файла (один лист) с {len(rows)} строк(ами)")

    # Создаем DataFrame
    df = pd.DataFrame(rows, columns=columns)
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаление информации о часовом поясе
    # Excel не поддерживает datetimes с timezone. 
    # Мы используем 'datetimetz' для выбора колонок с часовым поясом.
    for col in df.select_dtypes(include=['datetimetz']).columns:
        df[col] = df[col].dt.tz_localize(None)

    # Создаем временный файл
    temp_file_path = os.path.join('/tmp', f'tmp{uuid.uuid4().hex}.xlsx')
    
    try:
        # NOTE: Предполагаем, что openpyxl установлен для работы с ExcelWriter
        writer = pd.ExcelWriter(temp_file_path, engine='openpyxl')
        df.to_excel(writer, index=False, sheet_name='Экспорт')
        writer.close() # Используем writer.close()
        logger.info(f"Excel-файл успешно создан: {temp_file_path}")
        return temp_file_path
    except Exception as e:
        logger.error(f"Ошибка при создании Excel-файла: {e}")
        # Переброс ошибки для логирования в основном обработчике
        raise ValueError(e)

def get_vladivostok_filename(prefix: str) -> str:
    """Возвращает имя файла с текущей датой и временем по Владивостоку."""
    # timezone теперь доступен
    tz = timezone('Asia/Vladivostok')
    now = datetime.now(tz)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"