import pandas as pd
import os
from datetime import datetime, timezone
from openpyxl.styles import PatternFill

def generate_dislocation_excel(df: pd.DataFrame) -> str:
    os.makedirs("temp_files", exist_ok=True)
    filename = f"dislocation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = os.path.join("temp_files", filename)

    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Дислокация')
        worksheet = writer.sheets['Дислокация']
        fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
        for cell in worksheet[1]:
            cell.fill = fill
        for col in worksheet.columns:
            max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

    return path