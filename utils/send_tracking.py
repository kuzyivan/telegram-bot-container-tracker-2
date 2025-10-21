# utils/send_tracking.py
import os
import pandas as pd
from io import BytesIO
from datetime import datetime
from typing import List, Any
import logging
from pytz import timezone 
import uuid 
# Для работы с форматированием нам нужен openpyxl
import openpyxl 
# Также нам нужна временная копия io, чтобы Pandas мог корректно работать с openpyxl
from pandas.io.formats.excel import ExcelWriter

logger = logging.getLogger(__name__)

def create_excel_file(rows: List[List[Any]], columns: List[str]) -> str:
    """Создает временный Excel-файл из списка строк и заголовков с форматированием."""
    logger.info(f"Создание Excel-файла (один лист) с форматированием, строк: {len(rows)}")

    # Создаем DataFrame
    df = pd.DataFrame(rows, columns=columns)
    
    # Удаление информации о часовом поясе
    for col in df.select_dtypes(include=['datetimetz']).columns:
        df[col] = df[col].dt.tz_localize(None)

    # Создаем временный файл
    temp_file_path = os.path.join('/tmp', f'tmp{uuid.uuid4().hex}.xlsx')
    
    try:
        # Используем openpyxl для доступа к объектам рабочей книги
        with pd.ExcelWriter(temp_file_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Дислокация')
            
            # --- ✅ ЛОГИКА ФОРМАТИРОВАНИЯ ---
            workbook = writer.book
            worksheet = writer.sheets['Дислокация']
            
            # 1. Форматирование заливки заголовка
            fill = openpyxl.styles.PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
            
            # 2. Форматирование выравнивания и жирности
            header_font = openpyxl.styles.Font(bold=True)
            
            # 3. Применение форматирования к первой строке (заголовкам)
            for cell in worksheet["1:1"]:
                cell.fill = fill
                cell.font = header_font
                
            # 4. Установка ширины столбцов
            for col_idx, column in enumerate(columns, 1):
                # Ширина столбца = максимальная длина текста в заголовке + небольшой запас
                max_length = len(column)
                
                # Получаем столбец по индексу (A, B, C, ...)
                column_letter = openpyxl.utils.get_column_letter(col_idx)
                
                # Устанавливаем ширину (с запасом 20-30%)
                adjusted_width = max_length * 1.5 + 5
                
                # Ограничиваем минимальную и максимальную ширину
                worksheet.column_dimensions[column_letter].width = max(15, min(adjusted_width, 50))

            # --- КОНЕЦ ЛОГИКИ ФОРМАТИРОВАНИЯ ---
            
        logger.info(f"Excel-файл успешно создан и отформатирован: {temp_file_path}")
        return temp_file_path
    
    except Exception as e:
        logger.error(f"❌ Ошибка при создании Excel-файла: {e}", exc_info=True)
        # Переброс ошибки для логирования в основном обработчике
        raise ValueError(e)

def get_vladivostok_filename(prefix: str) -> str:
    """Возвращает имя файла с текущей датой и временем по Владивостоку."""
    tz = timezone('Asia/Vladivostok')
    now = datetime.now(tz)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"