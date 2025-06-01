# tracking_utils.py
from pandas import DataFrame
from sqlalchemy.future import select
from models import Tracking
from db import SessionLocal

async def build_tracking_dataframe(containers: list[str]) -> DataFrame:
    rows = []
    async with SessionLocal() as session:
        for container in containers:
            result = await session.execute(
                select(Tracking).where(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
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
    return DataFrame(rows, columns=[
        'Номер контейнера', 'Станция отправления', 'Станция назначения',
        'Станция операции', 'Операция', 'Дата и время операции',
        'Номер накладной', 'Осталось км', 'Прогноз дней',
        'Номер вагона', 'Дорога'
    ])
