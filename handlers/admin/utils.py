# handlers/admin/utils.py
from telegram import Update
from telegram.ext import ContextTypes

# Импорт ADMIN_CHAT_ID из config.py
import sys
import os
# Добавляем корень проекта в путь, если он не был добавлен ранее
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..')) 
from config import ADMIN_CHAT_ID 
from logger import get_logger

logger = get_logger(__name__)

async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, что команду вызвал администратор."""
    user = update.effective_user
    if not user:
        logger.warning("Отказ в доступе к админ-команде: отсутствует user.")
        return False
    if user.id != ADMIN_CHAT_ID:
        if update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, "⛔ Доступ запрещён.")
        logger.warning(f"Отказ в доступе к админ-команде пользователю {user.id}")
        return False
    return True
