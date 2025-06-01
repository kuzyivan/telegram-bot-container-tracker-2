import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
import tempfile

def create_excel_file(rows, columns):
    """
    Универсальная функция формирования Excel-файла.
    rows: список списков (данные)
    columns: список названий столбцов
    Возвращает путь к временному .xlsx-файлу.
    """
    df = pd.DataFrame(rows, columns=columns)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Экспорт')
            worksheet = writer.sheets['Экспорт']

            # Стилизация шапки (цвет)
            header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
            for cell in worksheet[1]:
                cell.fill = header_fill

            # Автоширина столбцов
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

        return tmp.name

def get_vladivostok_filename(prefix="Дислокация"):
    """
    Генерирует имя файла по Владивостокскому времени (UTC+10).
    """
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    return f"{prefix} {vladivostok_time.strftime('%H-%M')}.xlsx"
