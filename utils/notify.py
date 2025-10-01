# utils/notify.py
import asyncio
from telegram import Bot
from telegram.error import TimedOut, NetworkError
from telegram.request import HTTPXRequest
from logger import get_logger
from config import TOKEN, ADMIN_CHAT_ID

logger = get_logger(__name__)

async def notify_admin(text: str, silent: bool = True):
    if not TOKEN:
        logger.critical("[notify_admin] TELEGRAM_TOKEN не задан! Невозможно отправить уведомление.")
        return

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=20.0,
    )
    bot = Bot(TOKEN, request=request)

    attempts = 3
    for i in range(attempts):
        try:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=text,
                # <<< ГЛАВНОЕ ИЗМЕНЕНИЕ ЗДЕСЬ >>>
                parse_mode="Markdown", 
                disable_notification=silent,
                read_timeout=60.0,
                write_timeout=60.0,
            )
            logger.info("[notify_admin] Сообщение админу отправлено.")
            return
        except (TimedOut, NetworkError) as e:
            logger.warning(f"[notify_admin] Временная ошибка отправки (попытка {i+1}/{attempts}): {e}")
            if i == attempts - 1:
                logger.exception("Не удалось отправить уведомление админу после ретраев.")
            else:
                await asyncio.sleep(2 ** i)
        except Exception as e:
            logger.exception("Не удалось отправить уведомление админу: %s", e)
            break