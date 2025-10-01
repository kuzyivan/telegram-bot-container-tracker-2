# utils/notify.py

import asyncio
from telegram import Bot
from telegram.error import TimedOut, NetworkError
from telegram.request import HTTPXRequest
from logger import get_logger
from config import TOKEN, ADMIN_CHAT_ID

logger = get_logger(__name__)

async def notify_admin(text: str, silent: bool = True):
    # <<< НАЧАЛО ИЗМЕНЕНИЙ: Добавляем проверку токена >>>
    if not TOKEN:
        logger.critical("[notify_admin] TELEGRAM_TOKEN не задан! Невозможно отправить уведомление.")
        return
    # <<< КОНЕЦ ИЗМЕНЕНИЙ >>>

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=20.0,
    )
    # Теперь Pylance "знает", что на этой строке TOKEN точно не None, и ошибка исчезнет
    bot = Bot(TOKEN, request=request)

    attempts = 3
    for i in range(attempts):
        try:
            # ВАЖНО: В коде train_event_notifier.py я убрал замену символов.
            # Правильнее указывать parse_mode здесь, если он нужен.
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=text,
                parse_mode="Markdown", # Используем Markdown, как в других частях бота
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