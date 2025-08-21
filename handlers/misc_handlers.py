from telegram import Update
from telegram.ext import ContextTypes
from db import get_tracked_containers_by_user, remove_user_tracking
from logger import get_logger

logger = get_logger(__name__)


# --- Показать отслеживаемые контейнеры пользователя ---
async def show_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    containers = await get_tracked_containers_by_user(user_id)
    if containers:
        msg = "Вы отслеживаете контейнеры:\n" + "\n".join(containers)
    else:
        msg = "У вас нет активных подписок на контейнеры."
    await update.message.reply_text(msg)


# --- Отмена всех подписок пользователя ---
async def cancel_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await remove_user_tracking(user_id)
    await update.message.reply_text("Все подписки успешно отменены.")
    logger.info(f"Пользователь {user_id} отменил все подписки.")