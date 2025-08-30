# mail_reader.py
from __future__ import annotations

import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ИСПРАВЛЕНИЕ: Импортируем AND из его подмодуля imap_tools.query
from imap_tools.query import AND

from logger import get_logger
from services.imap_service import ImapService
from services.container_importer import import_loaded_and_dispatch_from_excel

logger = get_logger(__name__)

_mail_check_lock = asyncio.Lock()
TERMINAL_DOWNLOAD_FOLDER = "/root/AtermTrackBot/download_container"


def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """
    Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ со смещением.
    """
    tz = ZoneInfo("Asia/Vladivostok")
    target_date = datetime.now(tz) - timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")


async def fetch_terminal_excel_and_process() -> dict | None:
    """
    Основная логика: ищет и импортирует отчет "Executive summary".
    """
    imap = ImapService()
    filepath = None
    stats = None

    today_str = _get_vladivostok_date_str(days_offset=0)
    logger.info(f"Ищу 'Executive summary' за сегодня ({today_str})...")
    criteria_today = AND(from_="aterminal@effex.ru", subject=f"Executive summary {today_str}")
    filepath = await asyncio.to_thread(
        imap.download_latest_attachment,
        criteria_today,
        TERMINAL_DOWNLOAD_FOLDER
    )

    if not filepath:
        yesterday_str = _get_vladivostok_date_str(days_offset=1)
        logger.info(f"Отчет за сегодня не найден. Ищу 'Executive summary' за вчера ({yesterday_str})...")
        criteria_yesterday = AND(from_="aterminal@effex.ru", subject=f"Executive summary {yesterday_str}")
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            criteria_yesterday,
            TERMINAL_DOWNLOAD_FOLDER
        )

    if not filepath:
        logger.info("Актуальный файл 'Executive summary' не найден.")
        return None

    try:
        logger.info(f"Найден файл {filepath}. Запускаю импорт в terminal_containers...")
        added_count, sheets_processed = await import_loaded_and_dispatch_from_excel(filepath)
        stats = {
            "file_name": os.path.basename(filepath),
            "total_added": added_count,
            "sheets_processed": sheets_processed,
        }
        logger.info(f"Импорт из '{os.path.basename(filepath)}' завершен. Добавлено: {added_count}, листов: {sheets_processed}.")
        return stats
    except Exception as e:
        logger.error(f"Ошибка при импорте файла '{filepath}': {e}", exc_info=True)
        raise


async def check_mail():
    """
    Плановая задача, запускаемая каждые 20 минут.
    """
    logger.info("📬 [Scheduler] Запущена плановая проверка почты...")
    if _mail_check_lock.locked():
        logger.info("🔒 Проверка почты уже выполняется — текущий запуск пропускается.")
        return

    async with _mail_check_lock:
        try:
            await fetch_terminal_excel_and_process()
        except Exception as e:
            logger.error(f"❌ Ошибка в процессе выполнения check_mail: {e}", exc_info=True)

    logger.info("📬 [Scheduler] Плановая проверка почты завершена.")