# scheduler.py
from datetime import datetime, time
from typing import Optional, Mapping
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

import config
from utils.notify import notify_admin
from logger import get_logger
from services.notification_service import NotificationService
from services.dislocation_importer import check_and_process_dislocation
from services.terminal_importer import check_and_process_terminal_report
from populate_stations_cache import job_populate_stations_cache

logger = get_logger(__name__)
TZ = timezone("Asia/Vladivostok")

JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
scheduler = AsyncIOScheduler(timezone=TZ, job_defaults=JOB_DEFAULTS)

def _format_terminal_import_message(started_dt: datetime, stats: Optional[Mapping] = None) -> str:
    """Форматирует сообщение для лога и уведомления."""
    header = "✅ <b>Обновление базы терминала завершено</b>\n"
    base = f"<b>Время (Владивосток):</b> {started_dt.strftime('%d.%m %H:%M')}\n"
    
    if not stats: 
        logger.info("[Terminal Import] Отчет: База терминала обновлена, но без статистики.")
        return header + base
        
    key_map = [("file_name", "Файл"), ("sheets_processed", "Листов обработано"), ("total_added", "Добавлено новых")]
    pretty = [f"<b>{title}:</b> {stats[key]}" for key, title in key_map if key in stats]
    
    summary_log = f"[Terminal Import] Сводка: Файл={stats.get('file_name', 'н/д')}, Добавлено={stats.get('total_added', 0)}, Листов={stats.get('sheets_processed', 0)}"
    logger.info(summary_log)
    
    return header + base + "\n".join(pretty)

async def job_send_notifications(bot, target_time: time):
    """Задача на рассылку уведомлений."""
    time_str = target_time.strftime('%H:%M')
    logger.info(f"🔔 Запуск задачи на рассылку для {time_str}")
    
    service = NotificationService(bot)
    try:
        logger.info(f"[Notification] Инициация рассылки для времени {time_str}...")
        
        sent_count, total_count = await service.send_scheduled_notifications(target_time)
        
        logger.info(f"✅ [Notification] Рассылка для {time_str} завершена. Отправлено: {sent_count}/{total_count}.")
        
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка в задаче рассылки для {time_str}: {e}", exc_info=True)


# ✅ НОВАЯ ФУНКЦИЯ: Проверка при запуске (для немедленного вызова)
async def job_dislocation_check_on_start():
    logger.info("⚡️ Scheduler: Запуск ПЕРВОНАЧАЛЬНОЙ проверки дислокации (при старте)...")
    try:
        await check_and_process_dislocation()
        logger.info("✅ Scheduler: Первоначальная проверка дислокации завершена.")
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче ПЕРВОНАЧАЛЬНОЙ проверки дислокации: {e}", exc_info=True)


# ПЕРИОДИЧЕСКАЯ проверка
async def job_periodic_dislocation_check():
    """Задача на проверку почты и обработку дислокации."""
    logger.info("🕒 Scheduler: Запуск периодической проверки дислокации...")
    try:
        logger.info("[Dislocation Import] Запуск проверки почты и обработки...")
        
        await check_and_process_dislocation()
        
        logger.info("✅ Scheduler: Периодическая проверка дислокации завершена.")
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче проверки дислокации: {e}", exc_info=True)

async def job_daily_terminal_import():
    """Задача на ежедневный импорт базы терминала."""
    logger.info("🕒 Scheduler: Запуск ежедневного импорта базы терминала...")
    started = datetime.now(TZ)
    try:
        logger.info("[Terminal Import] Запуск проверки почты и импорта...")
        
        stats = await check_and_process_terminal_report()
        
        text = _format_terminal_import_message(started_dt=started, stats=stats)
        
        if stats and stats.get('total_added', 0) > 0:
             await notify_admin(text, silent=True, parse_mode="HTML")
             
        logger.info("✅ Scheduler: Ежедневный импорт базы терминала завершен.")
             
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче импорта терминала: {e}", exc_info=True)
        error_message = (f"❌ <b>Ошибка обновления базы терминала</b>\n<b>Время:</b> {started.strftime('%d.%m %H:%M')}\n<code>{e}</code>")
        await notify_admin(error_message, silent=False, parse_mode="HTML")

def start_scheduler(bot):
    """Регистрирует и запускает все задачи планировщика."""
    scheduler.add_job(job_send_notifications, 'cron', hour=9, minute=0, args=[bot, time(9, 0)], id="notify_for_09", replace_existing=True, jitter=600)
    scheduler.add_job(job_send_notifications, 'cron', hour=16, minute=0, args=[bot, time(16, 0)], id="notify_for_16", replace_existing=True, jitter=600)
    scheduler.add_job(job_periodic_dislocation_check, 'cron', minute='*/20', id="dislocation_check_20min", replace_existing=True, jitter=10) 
    scheduler.add_job(job_daily_terminal_import, 'cron', hour=8, minute=30, id="terminal_import_0830", replace_existing=True, jitter=10)

    # --- ✅ Блок фонового обновления кэша станций OSM отключен ---
    # if config.STATIONS_CACHE_CRON_SCHEDULE:
    #     try:
    #         trigger = CronTrigger.from_crontab(config.STATIONS_CACHE_CRON_SCHEDULE, timezone=TZ)
    #         scheduler.add_job(job_populate_stations_cache, trigger, id="stations_cacher_periodic", replace_existing=True, jitter=120)
    #         logger.info(f"🟢 Задача кеширования станций OSM запланирована: '{config.STATIONS_CACHE_CRON_SCHEDULE}'")
    #     except Exception as e:
    #         logger.error(f"❌ Не удалось запланировать задачу кеширования станций: {e}")
    # else:
    #     logger.info("ℹ️ Фоновое кеширование станций OSM отключено в конфигурации.")
    
    scheduler.start()
    logger.info("🟢 Планировщик запущен со всеми задачами.")
    local_time = datetime.now(TZ)
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    logger.info(f"🕒 Время по UTC: {datetime.utcnow()}")
    
    # ✅ ВОЗВРАЩАЕМ ФУНКЦИЮ ДЛЯ ЗАПУСКА В post_init
    return job_dislocation_check_on_start