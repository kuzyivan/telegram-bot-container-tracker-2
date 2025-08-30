# scheduler.py
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, time
from typing import Any, Callable, Optional, Mapping

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from mail_reader import check_mail, fetch_terminal_excel_and_process
from utils.notify import notify_admin
from logger import get_logger
from services.notification_service import NotificationService

# =========================
# Константы и общие настройки
# =========================
logger = get_logger(__name__)
TZ = timezone("Asia/Vladivostok")

# Параметры по умолчанию для всех джобов
JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 300,
}

# Единые ID задач
JOB_ID_MAIL_EVERY_20 = "mail_check_every_20"
JOB_ID_IMPORT_08_30 = "terminal_import_08_30"
JOB_ID_NOTIFY_FOR_09 = "notify_for_09"
JOB_ID_NOTIFY_FOR_16 = "notify_for_16"

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

def _format_terminal_import_message(started_dt: datetime, stats: Optional[Mapping] = None) -> str:
    """Формирует сообщение админу по результатам импорта терминальной базы."""
    header = "✅ <b>Обновление базы терминала завершено</b>\n"
    base = f"<b>Время (Владивосток):</b> {started_dt.strftime('%d.%m %H:%M')}\n"

    if not stats or not isinstance(stats, Mapping):
        return header + base
    
    key_map = [
        ("file_name", "Файл"), ("sheets_processed", "Листов обработано"), ("duration_sec", "Длительность, сек"),
        ("total_rows", "Строк обработано"), ("total_added", "Добавлено всего"), ("total_updated", "Обновлено всего"),
    ]
    pretty = [f"<b>{title}:</b> {stats[key]}" for key, title in key_map if key in stats]
    
    body = "\n".join(pretty)
    return header + base + (body + "\n" if body else "")

# =========================
# Джобы (jobs)
# =========================
async def job_check_mail():
    """Проверяет почту на наличие новых трекинг-файлов."""
    logger.info("📬 [job_check_mail] Старт плановой проверки почты.")
    try:
        await _maybe_await(check_mail)
        logger.info("✅ [job_check_mail] Проверка почты завершена.")
    except Exception as e:
        logger.error(f"❌ [job_check_mail] Ошибка: {e}", exc_info=True)

async def job_daily_terminal_import():
    """Импортирует данные из терминального отчета Executive summary."""
    logger.info("📥 [job_daily_terminal_import] 08:30 — запуск импорта Executive summary")
    started = datetime.now(TZ)
    try:
        stats = await _maybe_await(fetch_terminal_excel_and_process)
        logger.info("✅ [job_daily_terminal_import] Импорт успешно завершён.")
        
        text = _format_terminal_import_message(started_dt=started, stats=stats)
        await notify_admin(text, silent=True)
        logger.info("[job_daily_terminal_import] Администратор уведомлён об успешном обновлении.")
    except Exception as e:
        logger.error(f"❌ [job_daily_terminal_import] Ошибка импорта: {e}", exc_info=True)
        error_message = (
            f"❌ <b>Ошибка обновления базы терминала</b>\n"
            f"<b>Время (Владивосток):</b> {started.strftime('%d.%m %H:%M')}\n"
            f"<code>{e}</code>"
        )
        await notify_admin(error_message, silent=False)
        logger.error("[job_daily_terminal_import] Администратор уведомлён об ошибке.")

async def job_send_notifications(bot, target_time: time):
    """
    Задача-обертка, которая создает экземпляр сервиса уведомлений и запускает рассылку.
    """
    logger.info(f"🔔 Запуск задачи на рассылку для {target_time.strftime('%H:%M')}")
    service = NotificationService(bot)
    try:
        await service.send_scheduled_notifications(target_time)
        logger.info(f"✅ Задача на рассылку для {target_time.strftime('%H:%M')} завершена.")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка в задаче рассылки для {target_time.strftime('%H:%M')}: {e}", exc_info=True)

# =========================
# Публичная функция запуска
# =========================
def start_scheduler(bot):
    """
    Регистрирует и запускает все задачи планировщика.
    """
    # 1) Рассылки в 09:00 и 16:00
    scheduler.add_job(
        job_send_notifications,
        trigger='cron', hour=9, minute=0,
        args=[bot, time(9, 0)],
        id=JOB_ID_NOTIFY_FOR_09,
        replace_existing=True,
        jitter=10,
    )
    scheduler.add_job(
        job_send_notifications,
        trigger='cron', hour=16, minute=0,
        args=[bot, time(16, 0)],
        id=JOB_ID_NOTIFY_FOR_16,
        replace_existing=True,
        jitter=10,
    )

    # 2) Проверка почты каждые 20 минут
    scheduler.add_job(
        job_check_mail,
        trigger='cron', minute='*/20',
        id=JOB_ID_MAIL_EVERY_20,
        replace_existing=True,
        jitter=10,
    )

    # 3) Импорт терминальной базы строго в 08:30
    scheduler.add_job(
        job_daily_terminal_import,
        trigger='cron', hour=8, minute=30,
        id=JOB_ID_IMPORT_08_30,
        replace_existing=True,
        jitter=10,
    )

    scheduler.start()
    logger.info("🟢 Планировщик запущен. Задачи: почта */20, импорт 08:30, рассылки 09:00/16:00.")

    local_time = datetime.now(TZ)
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    logger.info(f"🕒 Время по UTC: {datetime.utcnow()}")