# services/terminal_importer.py
import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from imap_tools.query import AND

from logger import get_logger
from services.imap_service import ImapService
from services.container_importer import import_loaded_and_dispatch_from_excel

logger = get_logger(__name__)
TERMINAL_DOWNLOAD_FOLDER = "/root/AtermTrackBot/download_container"

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ."""
    tz = ZoneInfo("Asia/Vladivostok")
    target_date = datetime.now(tz) - timedelta(days=abs(days_offset))
    return target_date.strftime("%d.%m.%Y")

async def check_and_process_terminal_report() -> dict | None:
    """
    Основная логика: ищет и импортирует отчет "Executive summary".
    Сначала ищет отчет за сегодня, если не находит - за вчера.
    Возвращает словарь со статистикой импорта или None.
    """
    imap = ImapService()
    filepath = None

    # 1. Попытка найти отчет за сегодня
    today_str = _get_vladivostok_date_str(0)
    logger.info(f"📥 [Terminal] Ищу 'Executive summary' за сегодня ({today_str})...")
    criteria = AND(from_="aterminal@effex.ru", subject=f"Executive summary {today_str}")
    filepath = await asyncio.to_thread(
        imap.download_latest_attachment, criteria, TERMINAL_DOWNLOAD_FOLDER
    )

    # 2. Если за сегодня нет, попытка найти за вчера
    if not filepath:
        yesterday_str = _get_vladivostok_date_str(1)
        logger.info(f"[Terminal] Отчет за сегодня не найден. Ищу за вчера ({yesterday_str})...")
        criteria = AND(from_="aterminal@effex.ru", subject=f"Executive summary {yesterday_str}")
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment, criteria, TERMINAL_DOWNLOAD_FOLDER
        )

    if not filepath:
        logger.info("[Terminal] Актуальный файл 'Executive summary' не найден.")
        return None

    # 3. Если файл найден, запускаем импорт
    try:
        added, sheets = await import_loaded_and_dispatch_from_excel(filepath)
        stats = {
            "file_name": os.path.basename(filepath),
            "total_added": added,
            "sheets_processed": sheets,
        }
        logger.info(f"[Terminal] Импорт из '{os.path.basename(filepath)}' завершен. Добавлено: {added}, листов: {sheets}.")
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка при импорте файла терминала '{filepath}': {e}", exc_info=True)
        raise