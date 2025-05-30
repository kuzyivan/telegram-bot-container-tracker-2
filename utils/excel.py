import pandas as pd
import tempfile
from openpyxl.styles import PatternFill

def generate_dislocation_excel(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Дислокация')
        worksheet = writer.sheets['Дислокация']
        fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
        for cell in worksheet[1]:
            cell.fill = fill
        for col in worksheet.columns:
            max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
    return tmp.name