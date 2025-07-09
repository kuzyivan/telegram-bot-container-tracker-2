# utils/report_generator.py

from db import SessionLocal
from models import Tracking
from sqlalchemy.future import select
from utils.send_tracking import generate_excel_report, get_vladivostok_filename
from logger import get_logger

logger = get_logger(__name__)

columns = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

async def build_tracking_excel_file() -> tuple[bytes, str]:
    """Возвращает кортеж: (Excel-файл в виде байтов, имя файла)"""
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Tracking))
            rows = result.scalars().all()

        if not rows:
            logger.warning("[report_generator] Нет данных по отслеживанию.")
            return b"", ""

        data = []
        for track in rows:
            data.append([
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

        excel_bytes = generate_excel_report(data, columns)
        filename = get_vladivostok_filename("Дислокация")
        return excel_bytes, filename

    except Exception as e:
        logger.error(f"[report_generator] Ошибка генерации отчёта: {e}", exc_info=True)
        return b"", ""