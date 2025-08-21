from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from db import set_user_email
from logger import get_logger

logger = get_logger(__name__)

# Стейт для ConversationHandler
SET_EMAIL = range(1)

# === Команда /set_email ===
async def set_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, отправьте ваш email для уведомлений, или /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove()
    )
    return SET_EMAIL

# === Обработка введенного email ===
async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username or ""

    await set_user_email(telegram_id, username, email)
    await update.message.reply_text(
        f"Email {email} успешно сохранён ✅",
        reply_markup=ReplyKeyboardRemove()
    )
    logger.info(f"Email {email} сохранён для пользователя {telegram_id} ({username})")
    return ConversationHandler.END

# === Обработка отмены ===
async def cancel_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ввод email отменён.",
        reply_markup=ReplyKeyboardRemove()
    )
    logger.info(f"Пользователь {update.effective_user.id} отменил ввод email.")
    return ConversationHandler.END