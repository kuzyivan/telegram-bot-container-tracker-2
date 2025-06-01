from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time
from models import TrackingSubscription
from db import SessionLocal
import logging

from utils.send_tracking import get_tracking_rows, create_excel_file, get_vladivostok_filename
from mail_reader import check_mail

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

        for sub in subscriptions:
            rows = await get_tracking_rows(sub.containers)
            if not rows:
                await bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(sub.containers)}")
                continue

            file_path = create_excel_file(rows)
            filename = get_vladivostok_filename()
            with open(file_path, "rb") as f:
                await bot.send_document(
                    chat_id=sub.user_id,
                    document=f,
                    filename=filename
                )
