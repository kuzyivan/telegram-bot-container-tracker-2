import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
import tempfile
import re
from logger import get_logger

logger = get_logger(__name__)

def create_excel_file(rows, columns):
    """
    Однолистовой Excel-файл.
    rows: список списков с данными
    columns: список названий столбцов
    """
    logger.info("Создание Excel-файла (один лист) с %d строк(ами)", len(rows))
    try:
        df = pd.DataFrame(rows, columns=columns)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Экспорт')
                worksheet = writer.sheets['Экспорт']
                header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for cell in worksheet[1]:
                    cell.fill = header_fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
            logger.info("Excel-файл успешно создан: %s", tmp.name)
            return tmp.name
    except Exception as e:
        logger.error("Ошибка при создании Excel-файла: %s", e, exc_info=True)
        raise

def clean_sheet_name(name):
    clean = re.sub(r'[:\\/?*\[\]]', '_', str(name))[:31]
    logger.debug("Очищено имя листа: %s -> %s", name, clean)
    return clean

def create_excel_multisheet(data_per_user, columns):
    """
    Мультилистовой Excel-файл по пользователям.
    data_per_user: dict{user_label: [rows]}
    columns: список названий столбцов
    """
    logger.info("Создание мультилистового Excel-файла для %d пользователей", len(data_per_user))
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                for user_label, rows in data_per_user.items():
                    sheet_name = clean_sheet_name(user_label)
                    df = pd.DataFrame(rows, columns=columns)
                    df.to_excel(writer, index=False, sheet_name=sheet_name)
                    worksheet = writer.sheets[sheet_name]
                    header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                    for cell in worksheet[1]:
                        cell.fill = header_fill
                    for col in worksheet.columns:
                        max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                        worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
            logger.info("Мультилистовый Excel-файл успешно создан: %s", tmp.name)
            return tmp.name
    except Exception as e:
        logger.error("Ошибка при создании мультилистового Excel-файла: %s", e, exc_info=True)
        raise

def get_vladivostok_filename(prefix="Слежение контейнеров"):
    """
    Генерирует имя файла по Владивостокскому времени (UTC+10).
    """
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    filename = f"{prefix} {vladivostok_time.strftime('%H-%M')}.xlsx"
    logger.debug("Сгенерировано имя файла для Владивостока: %s", filename)
    return filename