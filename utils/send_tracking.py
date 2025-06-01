import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
import tempfile
from models import Tracking
from sqlalchemy.future import select
from db import SessionLocal

COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

async def get_tracking_rows(container_numbers):
    rows = []
    async with SessionLocal() as session:
        for container in container_numbers:
            result = await session.execute(
                select(Tracking).filter(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
            )
            track = result.scalars().first()
            if track:
                rows.append([
                    track.container_number,
                    track.from_station,
                    track.to_station,
                    track.current_station,
                    track.operation,
                    track.operation_date,
                    track.waybill,
                    track.km_left,
                    track.forecast_days,
                    track.wagon_number,
                    track.operation_road
                ])
    return rows

def create_excel_file(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Дислокация')
            worksheet = writer.sheets['Дислокация']
            header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
            for cell in worksheet[1]:
                cell.fill = header_fill
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
        return tmp.name

def get_vladivostok_filename():
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    return f"Дислокация {vladivostok_time.strftime('%H-%M')}.xlsx"
