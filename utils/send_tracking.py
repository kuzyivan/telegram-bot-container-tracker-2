# utils/send_tracking.py
import os
import pandas as pd
from io import BytesIO
from datetime import datetime
from typing import List, Any
import logging
from pytz import timezone 
import uuid 
import openpyxl 
from pandas import ExcelWriter 
import openpyxl.utils
# ✅ НОВЫЙ ИМПОРТ: Стили для заголовка
from openpyxl.styles import Font, PatternFill, Alignment

logger = logging.getLogger(__name__)

def create_excel_file_from_strings(rows: List[List[Any]], columns: List[str]) -> str:
    """
    Создает временный Excel-файл из списка строк и заголовков.
    Эта функция считает, что все данные уже преобразованы в строки.
    """
    logger.info(f"Создание Excel-файла (один лист) с форматированием, строк: {len(rows)}")

    # --- ✅ ИЗМЕНЕНИЕ: Создаем DataFrame с типом 'object' (строки) ---
    # Это предотвращает "умное" преобразование дат/чисел со стороны pandas
    df = pd.DataFrame(rows, columns=columns, dtype='object')
    
    # --- ✅ ИЗМЕНЕНИЕ: Заменяем None на пустые строки "" ---
    # Pandas может вставить 'None' или 'NaN' как текст
    df.fillna("", inplace=True)

    # Создаем временный файл
    temp_file_path = os.path.join('/tmp', f'tmp{uuid.uuid4().hex}.xlsx')
    
    try:
        # Используем pandas.ExcelWriter
        with ExcelWriter(temp_file_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Дислокация')
            
            # --- ЛОГИКА ФОРМАТИРОВАНИЯ (только заголовок и ширина) ---
            workbook = writer.book
            worksheet = writer.sheets['Дислокация']
            
            fill = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
            header_font = Font(bold=True)
            
            # Применение форматирования к первой строке (заголовкам)
            for cell in worksheet["1:1"]:
                cell.fill = fill
                cell.font = header_font
                
            # --- ✅ УПРОЩЕНИЕ: Убрана сложная логика форматирования дат ---
            # (Так как мы теперь передаем строки, она не нужна)
            
            # Установка ширины столбцов
            for col_idx, column_name in enumerate(columns, 1):
                column_letter = openpyxl.utils.get_column_letter(col_idx)
                
                # Устанавливаем ширину на основе заголовка или 20 (для дат)
                if 'дата' in column_name.lower():
                     adjusted_width = 20
                else:
                     adjusted_width = len(column_name) * 1.5 + 5
                
                worksheet.column_dimensions[column_letter].width = max(15, min(adjusted_width, 50))

            # --- КОНЕЦ УПРОЩЕНИЯ ---
            
        logger.info(f"Excel-файл успешно создан и отформатирован: {temp_file_path}")
        return temp_file_path
    
    except Exception as e:
        logger.error(f"❌ Ошибка при создании Excel-файла: {e}", exc_info=True)
        raise ValueError(e)

# --- ✅ ВАЖНО: Переименовываем старую функцию, чтобы она не вызывалась ---
# (Она остается здесь на случай, если ее вызывает другой сервис, например, notification_service)
def create_excel_file(rows: List[List[Any]], columns: List[str]) -> str:
    """
    (ОБЕРТКА) Вызывает новую функцию create_excel_file_from_strings.
    """
    logger.warning("Вызвана устаревшая функция create_excel_file, перенаправляю на create_excel_file_from_strings")
    
    # Мы должны убедиться, что все данные - строки
    string_rows = []
    for row in rows:
        string_rows.append([str(item) if item is not None else "" for item in row])
        
    return create_excel_file_from_strings(string_rows, columns)


def get_vladivostok_filename(prefix: str) -> str:
    """Возвращает имя файла с текущей датой и временем по Владивостоку."""
    tz = timezone('Asia/Vladivostok')
    now = datetime.now(tz)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"