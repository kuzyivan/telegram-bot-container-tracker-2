# scheduler.py
from __future__ import annotations
from datetime import datetime, time
from typing import Optional, Mapping
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from utils.notify import notify_admin
from logger import get_logger
from services.notification_service import NotificationService
from services.dislocation_importer import check_and_process_dislocation
from services.terminal_importer import check_and_process_terminal_report

logger = get_logger(__name__)
TZ = timezone("Asia/Vladivostok")

JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
scheduler = AsyncIOScheduler(timezone=TZ, job_defaults=JOB_DEFAULTS)


def _format_terminal_import_message(started_dt: datetime, stats: Optional[Mapping] = None) -> str:
    header = "✅ <b>Обновление базы терминала завершено</b>\n"
    base = f"<b>Время (Владивосток):</b> {started_dt.strftime('%d.%m %H:%M')}\n"
    if not stats: return header + base
    key_map = [
        ("file_name", "Файл"), ("sheets_processed", "Листов обработано"),
        ("total_added", "Добавлено новых"),
    ]
    pretty = [f"<b>{title}:</b> {stats[key]}" for key, title in key_map if key in stats]
    return header + base + "\n".join(pretty)


async def job_send_notifications(bot, target_time: time):
    logger.info(f"🔔 Запуск задачи на рассылку для {target_time.strftime('%H:%M')}")
    service = NotificationService(bot)
    try:
        await service.send_scheduled_notifications(target_time)
        logger.info(f"✅ Задача на рассылку для {target_time.strftime('%H:%M')} завершена.")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка в задаче рассылки для {target_time.strftime('%H:%M')}: {e}", exc_info=True)


async def job_periodic_dislocation_check():
    logger.info("Scheduler: Запуск периодической проверки дислокации...")
    try:
        await check_and_process_dislocation()
        logger.info("Scheduler: Периодическая проверка дислокации завершена.")
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче проверки дислокации: {e}", exc_info=True)


async def job_daily_terminal_import():
    logger.info("Scheduler: Запуск ежедневного импорта базы терминала...")
    started = datetime.now(TZ)
    try:
        stats = await check_and_process_terminal_report()
        if stats:
            text = _format_terminal_import_message(started_dt=started, stats=stats)
            await notify_admin(text, silent=True)
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче импорта терминала: {e}", exc_info=True)
        error_message = (
            f"❌ <b>Ошибка обновления базы терминала</b>\n"
            f"<b>Время:</b> {started.strftime('%d.%m %H:%M')}\n"
            f"<code>{e}</code>"
        )
        await notify_admin(error_message, silent=False)


def start_scheduler(bot):
    """
    Регистрирует и запускает все задачи планировщика.
    """
    # 1) Рассылки пользователям
    scheduler.add_job(
        job_send_notifications, 'cron', hour=9, minute=0,
        args=[bot, time(9, 0)], id="notify_for_09", replace_existing=True,
        jitter=600  # <<< РЕКОМЕНДАЦИЯ: 600 секунд (10 минут)
    )
    scheduler.add_job(
        job_send_notifications, 'cron', hour=16, minute=0,
        args=[bot, time(16, 0)], id="notify_for_16", replace_existing=True,
        jitter=600  # <<< РЕКОМЕНДАЦИЯ: 600 секунд (10 минут)
    )

    # 2) Задача для проверки дислокации каждые 20 минут
    scheduler.add_job(
        job_periodic_dislocation_check, 'cron', minute='*/20',
        id="dislocation_check_20min", replace_existing=True, jitter=10
    )

    # 3) Задача для импорта базы терминала в 08:30
    scheduler.add_job(
        job_daily_terminal_import, 'cron', hour=8, minute=30,
        id="terminal_import_0830", replace_existing=True, jitter=10
    )

    scheduler.start()
    # <<< РЕКОМЕНДАЦИЯ: Обновленное сообщение в логе
    logger.info("🟢 Планировщик запущен с разделенными задачами и дрожанием (jitter).")
    local_time = datetime.now(TZ)
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    logger.info(f"🕒 Время по UTC: {datetime.utcnow()}")