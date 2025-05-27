from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import datetime, time, timedelta
from models import TrackingSubscription
from db import SessionLocal

scheduler = AsyncIOScheduler()

VLADIVOSTOK_OFFSET = timedelta(hours=10)

def start_scheduler(bot):
    scheduler.add_job(lambda: send_notifications(bot, time(9, 0)), 'cron', hour=23, minute=0)  # 09:00 VLAT
    scheduler.add_job(lambda: send_notifications(bot, time(16, 0)), 'cron', hour=6, minute=0)  # 16:00 VLAT
    scheduler.start()

async def send_notifications(bot, target_time: time):
    now_vlad = datetime.utcnow() + VLADIVOSTOK_OFFSET
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            text = f"📦 Отчёт по контейнерам {', '.join(sub.containers)}\n⏰ {target_time.strftime('%H:%M')} по Владивостоку"
            try:
                await bot.send_message(chat_id=sub.user_id, text=text)
            except Exception as e:
                print(f"❌ Ошибка отправки пользователю {sub.user_id}: {e}")
