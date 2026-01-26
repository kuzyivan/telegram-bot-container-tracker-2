# scheduler.py
import asyncio
import sys
from datetime import datetime, time, timedelta
from typing import Optional, Mapping
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from sqlalchemy import update

from db import SessionLocal
from models import ScheduledTrain

import config
from utils.notify import notify_admin
from logger import get_logger
from services.notification_service import NotificationService
from services.dislocation_importer import check_and_process_dislocation 
from services.terminal_importer import check_and_process_terminal_report
from populate_stations_cache import job_populate_stations_cache
from telegram import Bot

logger = get_logger(__name__)
# Устанавливаем часовой пояс Владивостока
TZ = timezone("Asia/Vladivostok") 

JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
scheduler = AsyncIOScheduler(timezone=TZ, job_defaults=JOB_DEFAULTS)

def _format_terminal_import_message(started_dt: datetime, stats: Optional[Mapping] = None) -> str:
    """Форматирует сообщение о завершении импорта терминала."""
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

async def job_send_notifications(bot: Bot, target_time: time):
    """Задача на рассылку плановых уведомлений."""
    time_str = target_time.strftime('%H:%M')
    logger.info(f"🔔 Запуск задачи на рассылку для {time_str}")
    
    service = NotificationService(bot)
    try:
        logger.info(f"[Notification] Инициация рассылки для времени {time_str}...")
        
        sent_count, total_count = await service.send_scheduled_notifications(target_time)
        
        logger.info(f"✅ [Notification] Рассылка для {time_str} завершена. Отправлено: {sent_count}/{total_count}.")
        
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка в задаче рассылки для {time_str}: {e}", exc_info=True)


async def job_dislocation_check_on_start(bot: Bot): 
    """Задача на ПЕРВОНАЧАЛЬНУЮ проверку дислокации (при старте)."""
    logger.info("⚡️ Scheduler: Запуск ПЕРВОНАЧАЛЬНОЙ проверки дислокации (при старте)...")
    try:
        await check_and_process_dislocation(bot) 
        logger.info("✅ Scheduler: Первоначальная проверка дислокации завершена.")
    except Exception as e:
        logger.error(f"❌ Scheduler: Ошибка в задаче ПЕРВОНАЧАЛЬНОЙ проверки дислокации: {e}", exc_info=True)


async def job_periodic_dislocation_check(bot: Bot):
    """Задача на периодическую проверку почты и обработку дислокации."""
    logger.info("🕒 Scheduler: Запуск периодической проверки дислокации...")
    try:
        logger.info("[Dislocation Import] Запуск проверки почты и обработки...")
        await check_and_process_dislocation(bot) 
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

async def job_cleanup_old_stocks():
    """
    Ежедневная очистка стоков у поездов, дата отправления которых была более 3 дней назад.
    """
    logger.info("🧹 Scheduler: Запуск очистки устаревших стоков...")
    # Очищаем, если прошло 3 дня (<= сегодня - 3 дня)
    cutoff_date = datetime.now(TZ).date() - timedelta(days=3)
    
    async with SessionLocal() as session:
        try:
            stmt = (
                update(ScheduledTrain)
                .where(ScheduledTrain.schedule_date <= cutoff_date)
                .where(ScheduledTrain.stock_info.isnot(None))
                .values(stock_info=None)
            )
            result = await session.execute(stmt)
            await session.commit()
            
            if result.rowcount > 0:
                logger.info(f"✅ Очищены стоки у {result.rowcount} поездов (дата рейса по {cutoff_date}).")
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке стоков: {e}", exc_info=True)

def start_scheduler(bot: Bot):
    """Регистрирует и запускает все задачи планировщика."""
    
    # 1. Плановые уведомления
    scheduler.add_job(job_send_notifications, 'cron', hour=9, minute=0, args=[bot, time(9, 0)], id="notify_for_09", replace_existing=True, jitter=600)
    scheduler.add_job(job_send_notifications, 'cron', hour=16, minute=0, args=[bot, time(16, 0)], id="notify_for_16", replace_existing=True, jitter=600)
    
    # 2. ПЕРИОДИЧЕСКАЯ ПРОВЕРКА ДИСЛОКАЦИИ (каждые 20 мин)
    scheduler.add_job(job_periodic_dislocation_check, 'cron', minute='*/20', args=[bot], id="dislocation_check_20min", replace_existing=True, jitter=10) 
    
    # 3. ЕЖЕДНЕВНЫЙ ИМПОРТ ТЕРМИНАЛА
    scheduler.add_job(job_daily_terminal_import, 'cron', hour=8, minute=30, id="terminal_import_0830", replace_existing=True, jitter=10)
    scheduler.add_job(job_daily_terminal_import, 'cron', hour=11, minute=30, id="terminal_import_1130", replace_existing=True, jitter=10)
    
    # 🔥 НОВЫЕ ЗАДАЧИ (БЕЗ ВЕДУЩЕГО НУЛЯ В МИНУТАХ!)
    #scheduler.add_job(job_daily_terminal_import, 'cron', hour=15, minute=55, id="terminal_import_1555", replace_existing=True, jitter=10)
    
    # Ваша попытка на 16:35 (исправлено с 05 на 35)
    #scheduler.add_job(job_daily_terminal_import, 'cron', hour=16, minute=35, id="terminal_import_1635", replace_existing=True, jitter=10)

    # 4. ОЧИСТКА СТАРЫХ СТОКОВ (Ежедневно в 17:10)
    scheduler.add_job(job_cleanup_old_stocks, 'cron', hour=17, minute=10, id="cleanup_stocks_1710", replace_existing=True, jitter=60)

    if config.STATIONS_CACHE_CRON_SCHEDULE: 
        try:
            trigger = CronTrigger.from_crontab(config.STATIONS_CACHE_CRON_SCHEDULE, timezone=TZ)
            scheduler.add_job(job_populate_stations_cache, trigger, id="stations_cacher_periodic", replace_existing=True, jitter=120)
            logger.info(f"🟢 Задача кеширования станций OSM запланирована: '{config.STATIONS_CACHE_CRON_SCHEDULE}'")
        except Exception as e:
            logger.error(f"❌ Не удалось запланировать задачу кеширования станций: {e}")
    else:
        logger.info("ℹ️ Фоновое кеширование станций OSM отключено в конфигурации.")
        
    scheduler.start()
    logger.info("🟢 Планировщик запущен со всеми задачами.")
    local_time = datetime.now(TZ)
    logger.info(f"🕒 Локальное время Владивостока: {local_time}")
    
    return job_dislocation_check_on_start

async def run_scheduler_standalone():
    """
    Функция для запуска планировщика как отдельного процесса.
    Инициализирует бота и запускает задачи.
    """
    logger.info("🚀 Запуск планировщика в автономном режиме...")
    
    # Инициализируем бота
    bot = Bot(token=config.TELEGRAM_TOKEN)
    try:
        me = await bot.get_me()
        logger.info(f"🤖 Бот инициализирован: @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при проверке токена бота: {e}")

    # Запускаем планировщик
    on_start_job = start_scheduler(bot)
    
    # Выполняем первоначальную проверку
    if on_start_job:
        await on_start_job(bot)
        
    # Держим цикл живым
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("🛑 Планировщик остановлен.")
        scheduler.shutdown()

if __name__ == "__main__":
    # Настройка логирования для автономного запуска
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(run_scheduler_standalone())
    except (KeyboardInterrupt, SystemExit):
        pass