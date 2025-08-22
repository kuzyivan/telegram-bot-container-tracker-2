# utils/notify.py
from telegram import Bot
from logger import get_logger
from config import TOKEN, ADMIN_CHAT_ID

logger = get_logger(__name__)

async def notify_admin(text: str, silent: bool = True):
    """
    Асинхронная отправка сообщения админу.
    silent=True — без звука (для штатных задач), silent=False — со звуком (для ошибок).
    """
    try:
        bot = Bot(TOKEN)
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode="HTML",
            disable_notification=silent
        )
        logger.info("[notify_admin] Сообщение админу отправлено.")
    except Exception as e:
        logger.exception("Не удалось отправить уведомление админу: %s", e)