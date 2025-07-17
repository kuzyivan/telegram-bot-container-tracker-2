from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from utils.send_tracking import (
    create_excel_file,
    get_vladivostok_filename,
    generate_excel_report
)
from utils.email_sender import send_to_email
from mail_reader import check_mail
from logger import get_logger

logger = get_logger(__name__)

scheduler = AsyncIOScheduler()

def start_scheduler(bot):
    scheduler.add_job(send_notifications, 'cron', hour=23, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=6, minute=0, args=[bot, time(16, 0)])
    scheduler.add_job(check_mail, 'cron', minute=20)
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
                'Номер контейнера', 'Станция отправления', 'Станция назначения',
                'Станция операции', 'Операция', 'Дата и время операции',
                'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
                'Номер вагона', 'Дорога операции'
            ]

            for sub in subscriptions:
                logger.info(f"📦 Обработка подписки: user_id={sub.user_id}, канал={sub.delivery_channel}, контейнеры={sub.containers}")

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

                containers_list = list(sub.containers) if isinstance(sub.containers, (list, tuple, set)) else []
                user_result = await session.execute(
                    select(User).where(User.id == sub.user_id)
                )
                user = user_result.scalar_one_or_none()

                # === РАССЫЛКА ПРИ ОТСУТСТВИИ ДАННЫХ ===
                if not rows:
                    msg = f"📭 Нет данных по контейнерам {', '.join(containers_list)}"
                    logger.warning(f"Нет данных для user_id={sub.user_id}, email={getattr(user, 'email', None)}")

                    if sub.delivery_channel in ["telegram", "both"]:
                        await bot.send_message(sub.user_id, msg)
                        logger.info(f"[Telegram] Отправлено сообщение о пустых данных для {sub.user_id}")

                    if sub.delivery_channel in ["email", "both"] and user is not None and getattr(user, "email", None):
                        try:
                            logger.info(f"[Email] Пытаюсь отправить сообщение об отсутствии данных на {user.email}")
                            await send_to_email(
                                str(user.email),
                                "Нет данных по отслеживанию",
                                msg,
                                None
                            )
                            logger.info(f"[Email] Сообщение об отсутствии данных отправлено на {user.email}")
                        except Exception as mail_err:
                            logger.error(f"[Email] Ошибка при отправке письма об отсутствии данных на {user.email}: {mail_err}", exc_info=True)
                    continue

                # === РАССЫЛКА ПРИ НАЛИЧИИ ДАННЫХ ===
                if sub.delivery_channel in ["telegram", "both"]:
                    try:
                        file_path = create_excel_file(rows, columns)
                        filename = get_vladivostok_filename()
                        with open(file_path, "rb") as f:
                            await bot.send_document(
                                chat_id=sub.user_id,
                                document=f,
                                filename=filename
                            )
                        logger.info(f"[Telegram] ✅ Отправлен файл {filename} пользователю {sub.user_id}")
                    except Exception as send_err:
                        logger.error(f"[Telegram] ❌ Ошибка при отправке файла пользователю {sub.user_id}: {send_err}", exc_info=True)

                if sub.delivery_channel in ["email", "both"] and user is not None and getattr(user, "email", None):
                    try:
                        excel_bytes = generate_excel_report(rows, columns)
                        logger.info(f"[Email] Пытаюсь отправить файл с отчётом на {user.email}")
                        await send_to_email(
                            to_email=str(user.email),
                            subject="Ваш отчёт по контейнерам",
                            text="Смотри вложение",
                            attachment_bytes=excel_bytes,
                            attachment_filename=get_vladivostok_filename()
                        )
                        logger.info(f"[Email] ✅ Отчёт по контейнерам успешно отправлен на {user.email}")
                    except Exception as mail_err:
                        logger.error(f"[Email] ❌ Ошибка при отправке email {user.email}: {mail_err}", exc_info=True)

    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при рассылке уведомлений: {e}", exc_info=True)