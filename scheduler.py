from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email
from mail_reader import check_mail
from logger import get_logger

logger = get_logger(__name__)

scheduler = AsyncIOScheduler()

def start_scheduler(bot):
    scheduler.add_job(send_notifications, 'cron', hour=23, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=6, minute=0, args=[bot, time(16, 0)])
    scheduler.add_job(check_mail, 'cron', minute=20)  # запуск каждый час в 20 минут 
    logger.info("🕓 Планировщик: задачи добавлены.")
    scheduler.start()
    logger.info("🟢 Планировщик запущен.")

async def send_notifications(bot, target_time: time):
    logger.info(f"🔔 Старт рассылки уведомлений для времени: {target_time}")
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
            )
            subscriptions = result.scalars().all()
            logger.info(f"Найдено подписок для уведомления: {len(subscriptions)}")
            columns = [
                "Контейнер",
                "Операция",
                "Дата операции",
                "Накладная",
                "Остаток км",
                "Прогноз дней",
                "Номер вагона",
                "Дорога операции"
            ]
            for sub in subscriptions:
                rows = []
                for track in sub.tracking:
                    rows.append([
                        track.container,
                        track.operation,
                        track.operation_date,
                        track.waybill,
                        track.km_left,
                        track.forecast_days,
                        track.wagon_number,
                        track.operation_road
                    ])
                if not rows:
                    containers_list = list(sub.containers) if isinstance(sub.containers, (list, tuple, set)) else []
                    await bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(containers_list)}")
                    logger.info(f"Нет данных для пользователя {sub.user_id} ({containers_list})")
                    continue
                file_path = create_excel_file(rows, columns)
                filename = get_vladivostok_filename()
                try:
                    with open(file_path, "rb") as f:
                        await bot.send_document(
                            chat_id=sub.user_id,
                            document=f,
                            filename=filename
                        )
                    logger.info(f"✅ Отправлен файл {filename} пользователю {sub.user_id}")
                except Exception as send_err:
                    logger.error(f"❌ Ошибка при отправке файла пользователю {sub.user_id}: {send_err}", exc_info=True)

                user_res = await session.execute(
                    select(User).where(User.telegram_id == sub.user_id)
                )
                user = user_res.scalars().first()
                if user and user.email_enabled and user.email:
                    await send_email(
                        to=user.email,
                        subject="Отчёт по контейнерам",
                        body="Во вложении файл с текущей информацией о контейнерах.",
                        attachments=[file_path],
                    )
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при рассылке уведомлений: {e}", exc_info=True)
