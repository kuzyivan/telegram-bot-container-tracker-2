from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from sqlalchemy import select as sync_select
from datetime import time, datetime
from pathlib import Path
from pytz import timezone

from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email
from mail_reader import check_mail
from services.container_importer import import_loaded_and_dispatch_from_excel
from logger import get_logger

logger = get_logger(__name__)

scheduler = AsyncIOScheduler(timezone=timezone("Asia/Vladivostok"))

def get_daily_excel_path():
    today = datetime.now().strftime("%d.%m.%Y")
    return Path(f"/root/AtermTrackBot/A-Terminal {today}.xlsx")

def check_dislocation_and_import():
    logger.info("🔄 Запущен общий планировщик проверки почты и импорта базы.")
    check_mail()
    now = datetime.now(timezone("Asia/Vladivostok"))
    if now.hour == 8 and now.minute == 30:
        logger.info("📥 Время для импорта Executive summary — выполняем импорт.")
        import_loaded_and_dispatch_from_excel(str(get_daily_excel_path()))
    else:
        logger.info("📭 Только проверка почты (не время импорта базы).")

def start_scheduler(bot):
    scheduler.add_job(send_notifications, 'cron', hour=23, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=6, minute=0, args=[bot, time(16, 0)])
    scheduler.add_job(check_dislocation_and_import, 'cron', minute='*/20')

    logger.info("🗓️ Общая задача проверки дислокации и импорта базы добавлена (каждые 20 минут).")
    scheduler.start()
    logger.info("🟢 Планировщик запущен.")

    local_time = datetime.now(timezone("Asia/Vladivostok"))
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    logger.info(f"🕒 Время по UTC: {datetime.utcnow()}")


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
                    containers_list = list(sub.containers) if isinstance(sub.containers, (list, tuple, set)) else []
                    await bot.send_message(sub.user_id, f"📝 Нет данных по контейнерам {', '.join(containers_list)}")
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
                    logger.info(f"✅ Отправлен файл {filename} пользователю {sub.user_id} в Telegram")
                except Exception as send_err:
                    logger.error(f"❌ Ошибка при отправке файла пользователю {sub.user_id} в Telegram: {send_err}", exc_info=True)

                user_result = await session.execute(
                    sync_select(User).where(User.telegram_id == sub.user_id, User.email_enabled == True)
                )
                user = user_result.scalar_one_or_none()

                if user and user.email:
                    try:
                        await send_email(
                            to=user.email,
                            attachments=[file_path]
                        )
                        logger.info(f"📧 Email с файлом отправлен на {user.email}")
                    except Exception as email_err:
                        logger.error(f"❌ Ошибка при отправке email на {user.email}: {email_err}", exc_info=True)
                else:
                    logger.info(f"📝 У пользователя {sub.user_id} нет активного email для рассылки.")

    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при рассылке уведомлений: {e}", exc_info=True)