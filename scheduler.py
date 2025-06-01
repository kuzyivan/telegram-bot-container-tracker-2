import os
import ast
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time, timedelta
from models import TrackingSubscription
from db import SessionLocal
from telegram import InputFile
from utils.excel import generate_dislocation_excel
from utils.tracking import build_tracking_dataframe
from mail_reader import check_mail

scheduler = AsyncIOScheduler()
VLADIVOSTOK_OFFSET = timedelta(hours=10)
logger = logging.getLogger(__name__)

def start_scheduler(bot):
    scheduler.add_job(lambda: send_notifications(bot, time(9, 0)), 'cron', hour=23, minute=0)
    scheduler.add_job(lambda: send_notifications(bot, time(16, 0)), 'cron', hour=6, minute=0)
    scheduler.add_job(check_mail, 'interval', minutes=30, id="mail_checking_30min")
    scheduler.start()

    for job in scheduler.get_jobs():
        print(f"[DEBUG] Scheduled job: {job}")


async def send_notifications(bot, target_time: time):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            try:
                containers = ast.literal_eval(sub.containers) if isinstance(sub.containers, str) else sub.containers
            except Exception:
                containers = []

            logger.info(f"[NOTIFY] user_id={sub.user_id}, username={sub.username}, containers={containers}")

            df = await build_tracking_dataframe(session, containers)

            if df.empty:
                await bot.send_message(sub.user_id, f"\U0001F4ED Нет данных по контейнерам {', '.join(containers)}")
                continue

            logger.debug(f"[DF] {df.shape[0]} строк, {df.shape[1]} колонок")
            logger.debug(f"[DF_PREVIEW]\n{df.head()}\n")

            file_path = generate_dislocation_excel(df)
            filename = os.path.basename(file_path)
            await bot.send_document(
                chat_id=sub.user_id,
                document=InputFile(file_path, filename=filename),
                caption="\U0001F4E6 Актуальная дислокация контейнеров"
            )