from pytz import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from sqlalchemy import select as sync_select
from datetime import time
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email
from mail_reader import check_mail
from services.container_importer import fetch_terminal_excel_and_process
from logger import get_logger
from pytz import timezone

logger = get_logger(__name__)

scheduler = AsyncIOScheduler(timezone=timezone("Asia/Vladivostok"))

def start_scheduler(bot):
    scheduler.add_job(send_notifications, 'cron', hour=23, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=6, minute=0, args=[bot, time(16, 0)])
    scheduler.add_job(check_mail, 'cron', minute=20)  # запуск каждый час в 20 минут 
    scheduler.add_job(fetch_terminal_excel_and_process, 'cron', hour=8, minute=30)
    logger.info("📅 Задача импорта Executive summary добавлена на 08:30 по Владивостоку.")
    logger.info("🕓 Планировщик: задачи добавлены.")
    scheduler.start()
    logger.info("🟢 Планировщик запущен.")
    from datetime import datetime
    import pytz
    local_time = datetime.now(pytz.timezone("Asia/Vladivostok"))
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
                    await bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(containers_list)}")
                    logger.info(f"Нет данных для пользователя {sub.user_id} ({containers_list})")
                    continue

                # 📁 Создание Excel-файла
                file_path = create_excel_file(rows, columns)
                filename = get_vladivostok_filename()

                # 📤 Отправка в Telegram
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

                # 📧 Отправка на Email (если настроено)
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
                    logger.info(f"📭 У пользователя {sub.user_id} нет активного email для рассылки.")

    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при рассылке уведомлений: {e}", exc_info=True)