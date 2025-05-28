from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import datetime, time, timedelta
from models import TrackingSubscription, Tracking
from db import SessionLocal
from telegram import InputFile
import pandas as pd
import tempfile

scheduler = AsyncIOScheduler()
VLADIVOSTOK_OFFSET = timedelta(hours=10)

def start_scheduler(application):
    # передаём весь application, чтобы была поддержка PTB 21+
    scheduler.add_job(lambda: send_notifications(application, time(9, 0)), 'cron', hour=23, minute=0)
    scheduler.add_job(lambda: send_notifications(application, time(16, 0)), 'cron', hour=6, minute=0)
    scheduler.start()

async def send_notifications(application, target_time: time):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            rows = []
            for container in sub.containers:
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

            if not rows:
                await application.bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(sub.containers)}")
                continue

            df = pd.DataFrame(rows, columns=[
                'Номер контейнера', 'Станция отправления', 'Станция назначения',
                'Станция операции', 'Операция', 'Дата и время операции',
                'Номер накладной', 'Осталось км', 'Прогноз дней',
                'Номер вагона', 'Дорога'
            ])

            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                df.to_excel(tmp.name, index=False)
                filename = f"Дислокация {datetime.utcnow().strftime('%H-%M')}.xlsx"
                await application.bot.send_document(chat_id=sub.user_id, document=InputFile(tmp.name), filename=filename)
