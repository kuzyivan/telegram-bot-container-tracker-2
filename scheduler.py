from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, time
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from sqlalchemy import select as sync_select
from pytz import timezone

from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email
from mail_reader import check_mail, fetch_terminal_excel_and_process
from logger import get_logger

# =========================
# Константы и общие настройки
# =========================
logger = get_logger(__name__)
TZ = timezone("Asia/Vladivostok")

# Параметры по умолчанию для всех джобов
JOB_DEFAULTS = {
    "coalesce": True,          # схлопывать накопившиеся пропуски в один запуск
    "max_instances": 1,        # не параллелить один и тот же джоб
    "misfire_grace_time": 300, # 5 минут на «опоздания»
}

# Единые ID задач
JOB_ID_MAIL_EVERY_20 = "mail_check_every_20"
JOB_ID_IMPORT_08_30  = "terminal_import_08_30"
JOB_ID_NOTIFY_FOR_09  = "notify_for_09"
JOB_ID_NOTIFY_FOR_16  = "notify_for_16"

# Глобальный планировщик (один на приложение)
scheduler = AsyncIOScheduler(timezone=TZ, job_defaults=JOB_DEFAULTS)


# =========================
# Вспомогательные функции
# =========================
async def _maybe_await(func: Callable[..., Any], *args, **kwargs):
    """
    Универсальный вызов: если func — coroutine function, await it;
    если sync — уводим в executor, чтобы не блокировать event loop.
    """
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# =========================
# Джобы (jobs)
# =========================
async def job_check_mail():
    """Проверка почты (tracking + попытка Executive summary)."""
    logger.info("📬 [job_check_mail] Старт плановой проверки почты.")
    try:
        await _maybe_await(check_mail)
        logger.info("✅ [job_check_mail] Проверка почты завершена.")
    except Exception as e:
        logger.error(f"❌ [job_check_mail] Ошибка: {e}", exc_info=True)


async def job_daily_terminal_import():
    """
    Импорт ежедневной терминальной базы. Запуск строго в 08:30 по Владивостоку.
    Скачивает сегодняшнее Executive summary в /root/AtermTrackBot/download_container
    и импортирует листы Loaded*/Dispatch* в terminal_containers.
    """
    logger.info("📥 [job_daily_terminal_import] 08:30 — запуск импорта Executive summary")
    try:
        await _maybe_await(fetch_terminal_excel_and_process)
        logger.info("✅ [job_daily_terminal_import] Импорт успешно завершён.")
    except Exception as e:
        logger.error(f"❌ [job_daily_terminal_import] Ошибка импорта: {e}", exc_info=True)


async def send_notifications(bot, target_time: time):
    """
    Рассылка уведомлений пользователям, подписанным на конкретное время.
    target_time — время из TrackingSubscription.notify_time (09:00 / 16:00 / произвольное).
    """
    logger.info(f"🔔 [send_notifications] Старт рассылки для времени: {target_time}")
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
            )
            subscriptions = result.scalars().all()
            logger.info(f"[send_notifications] Найдено подписок: {len(subscriptions)}")

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
                        select(Tracking)
                        .filter(Tracking.container_number == container)
                        .order_by(Tracking.operation_date.desc())
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
                    logger.info(f"[send_notifications] Нет данных для пользователя {sub.user_id} ({containers_list})")
                    continue

                # Создание Excel-файла с итогами
                file_path = create_excel_file(rows, columns)
                filename = get_vladivostok_filename()

                # Отправка в Telegram
                try:
                    with open(file_path, "rb") as f:
                        await bot.send_document(
                            chat_id=sub.user_id,
                            document=f,
                            filename=filename
                        )
                    logger.info(f"✅ [send_notifications] Отправлен файл {filename} пользователю {sub.user_id} (Telegram)")
                except Exception as send_err:
                    logger.error(f"❌ [send_notifications] Ошибка отправки файла в Telegram пользователю {sub.user_id}: {send_err}", exc_info=True)

                # Доп. рассылка на email (если включена)
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
                        logger.info(f"📧 [send_notifications] Email с файлом отправлен на {user.email}")
                    except Exception as email_err:
                        logger.error(f"❌ [send_notifications] Ошибка при отправке email на {user.email}: {email_err}", exc_info=True)
                else:
                    logger.info(f"[send_notifications] У пользователя {sub.user_id} нет активного email для рассылки.")
    except Exception as e:
        logger.critical(f"❌ [send_notifications] Критическая ошибка: {e}", exc_info=True)


# =========================
# Публичная функция запуска
# =========================
def start_scheduler(bot):
    """
    Регистрируем и запускаем все джобы планировщика.
    """
    # 1) Рассылки
    scheduler.add_job(
        send_notifications,
        trigger='cron',
        hour=23, minute=0,
        args=[bot, time(9, 0)],
        id=JOB_ID_NOTIFY_FOR_09,
        replace_existing=True,
        jitter=10,
    )
    scheduler.add_job(
        send_notifications,
        trigger='cron',
        hour=6, minute=0,
        args=[bot, time(16, 0)],
        id=JOB_ID_NOTIFY_FOR_16,
        replace_existing=True,
        jitter=10,
    )

    # 2) Проверка почты каждые 20 минут (tracking + попытка Executive summary)
    scheduler.add_job(
        job_check_mail,
        trigger='cron',
        minute='*/20',
        id=JOB_ID_MAIL_EVERY_20,
        replace_existing=True,
        jitter=10,
    )

    # 3) Импорт Executive summary строго в 08:30
    scheduler.add_job(
        job_daily_terminal_import,
        trigger='cron',
        hour=8, minute=30,
        id=JOB_ID_IMPORT_08_30,
        replace_existing=True,
        jitter=10,
    )

    scheduler.start()
    logger.info("🟢 Планировщик запущен. Задачи: почта */20, импорт 08:30, рассылки 23:00/06:00.")

    local_time = datetime.now(TZ)
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    logger.info(f"🕒 Время по UTC: {datetime.utcnow()}")