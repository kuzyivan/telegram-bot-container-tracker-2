from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time
from db import SessionLocal
from models import TrackingSubscription, Tracking
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from mail_reader import check_mail
import logging

scheduler = AsyncIOScheduler()

def start_scheduler(bot):
    scheduler.add_job(send_notifications, 'cron', hour=23, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=6, minute=0, args=[bot, time(16, 0)])
    scheduler.add_job(check_mail, 'interval', minutes=30)
    logging.info("🕓 Планировщик: задачи добавлены.")
    scheduler.start()

async def send_notifications(bot, target_time: time):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = result.scalars().all()
        columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ]
        for sub in subscriptions:
            rows = []
            for container in sub.containers:
                res = await session.execute(
                    select(Tracking).filter(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
                )
                track = res.scalars().first()
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
                await bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(sub.containers)}")
                continue
            file_path = create_excel_file(rows, columns)
            filename = get_vladivostok_filename()
            with open(file_path, "rb") as f:
                await bot.send_document(
                    chat_id=sub.user_id,
                    document=f,
                    filename=filename
                )
            logging.info(f"📤 Отправлено уведомление для {sub.user_id} ({sub.username or sub.user_id}) по времени {target_time}.")
            await session.commit()
# This code defines a scheduler for sending notifications about container tracking.
# It uses APScheduler to run tasks at specific times and checks for new emails periodically.
# The `send_notifications` function retrieves tracking data from the database and sends it to users via Telegram.
# The notifications are sent based on user subscriptions and the specified notification time.
# The scheduler is started with the `start_scheduler` function, which sets up the jobs.
# The code also includes logging to track the execution of scheduled tasks.
# The `SessionLocal` is used to manage database sessions, and the `TrackingSubscription` and `Tracking` models are used to query the database.
# The `create_excel_file` and `get_vladivostok_filename` functions are used to generate Excel files for the tracking data.
# The `check_mail` function is called periodically to check for new emails related to container tracking.
#             logging.info(f"📤 Отправлено уведомление для {sub.user_id} ({sub.username or sub.user_id}).")


