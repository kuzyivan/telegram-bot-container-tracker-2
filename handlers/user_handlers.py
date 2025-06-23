from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from db import (
    remove_user_tracking,
    get_tracked_containers_by_user,
    set_user_email,
)

import logging

logger = logging.getLogger(__name__)

# --- EMAIL ConversationHandler ---
SET_EMAIL = range(1)

async def set_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, введите ваш e-mail для получения отчётов. Пример: user@example.com\n"
        "Для отмены отправьте /cancel"
    )
    return SET_EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    # Минимальная валидация (расширь при необходимости)
    if "@" not in email or "." not in email:
        await update.message.reply_text("❗️Неверный формат e-mail. Попробуйте ещё раз или отправьте /cancel.")
        return SET_EMAIL
    await set_user_email(
        telegram_id=update.message.from_user.id,
        username=update.message.from_user.username,
        email=email
    )
    await update.message.reply_text(f"Ваш e-mail {email} сохранён. Теперь вы будете получать отчёты на почту.")
    logger.info(f"User {update.message.from_user.id} указал e-mail: {email}")
    return ConversationHandler.END

async def cancel_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ввод e-mail отменён.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ОСТАЛЬНЫЕ ХЕНДЛЕРЫ ИЗ ТВОЕГО КОДА ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(
        [["📦 Дислокация", "🔔 Задать слежение", "❌ Отмена слежения"]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров.\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(
        [["📦 Дислокация", "🔔 Задать слежение", "❌ Отмена слежения"]],
        resize_keyboard=True
    )
    await update.message.reply_text("Меню:", reply_markup=reply_markup)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👍")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для отслеживания.")
    elif text == "🔔 Задать слежение":
        containers = await get_tracked_containers_by_user(update.message.from_user.id)
        if containers:
            await update.message.reply_text(f"У вас уже установлены слежения: {', '.join(containers)}")
        else:
            await update.message.reply_text("У вас нет активных слежений. Введите номер контейнера для начала отслеживания.")
    elif text == "❌ Отмена слежения":
        await remove_user_tracking(update.message.from_user.id)
        await update.message.reply_text("Все слежения отменены.")
    else:
        await update.message.reply_text("Неизвестная команда. Используйте меню.")

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Заглушка: сюда вставляй свою обработку callback'ов кнопок
    await update.callback_query.answer("Обработка меню...")

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Заглушка для обработки reply-клавиатур
    await handle_message(update, context)

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Заглушка для инлайн-кнопок "Дислокация"
    await update.callback_query.answer("Инлайн-дислокация")

# --- конец файла ---