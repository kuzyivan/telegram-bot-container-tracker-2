import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
import tempfile

def create_excel_multisheet(data_per_user: dict, columns: list):
    """
    data_per_user: {user_label: [rows]}
    columns: list of columns for every sheet
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
            for user_label, rows in data_per_user.items():
                df = pd.DataFrame(rows, columns=columns)
                df.to_excel(writer, index=False, sheet_name=str(user_label)[:31])  # Excel sheet name limit = 31
                worksheet = writer.sheets[str(user_label)[:31]]
                header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for cell in worksheet[1]:
                    cell.fill = header_fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
        return tmp.name

def get_vladivostok_filename(prefix="Тестовая дислокация"):
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    return f"{prefix} {vladivostok_time.strftime('%H-%M')}.xlsx"
