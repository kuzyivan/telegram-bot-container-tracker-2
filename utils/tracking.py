import pandas as pd
from sqlalchemy import select
from models import Tracking

async def build_tracking_dataframe(containers: list[str], session) -> pd.DataFrame:
    rows = []
    for container in containers:
        result = await session.execute(
            select(Tracking).where(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
        )
        record = result.scalars().first()
        if record:
            rows.append([
                record.container_number,
                record.from_station,
                record.to_station,
                record.current_station,
                record.operation,
                record.operation_date,
                record.waybill,
                record.km_left,
                record.forecast_days,
                record.wagon_number,
                record.operation_road
            ])
    return pd.DataFrame(rows, columns=[
        'Номер контейнера', 'Станция отправления', 'Станция назначения',
        'Станция операции', 'Операция', 'Дата и время операции',
        'Номер накладной', 'Осталось км', 'Прогноз дней',
        'Номер вагона', 'Дорога'
    ])
