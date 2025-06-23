from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from db import (
    get_all_user_ids,
    get_tracked_containers_by_user,
    remove_user_tracking,
    set_user_email,
)
from logger import get_logger

logger = get_logger(__name__)

# Стейты для ConversationHandler
SET_EMAIL = range(1)

# --- Главное меню ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]
    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚢\n"
        "Выберите действие в меню:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# --- Email Conversation ---
async def set_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, отправьте ваш email для уведомлений, или /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove()
    )
    return SET_EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username or ""

    await set_user_email(telegram_id, username, email)
    await update.message.reply_text(
        f"Email {email} успешно сохранён ✅", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cancel_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ввод email отменён.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        await update.message.reply_text("Введите номер контейнера для слежения:")
    elif text == "❌ Отмена слежения":
        await cancel_my_tracking(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.")

# --- Inline кнопки (пример обработки) ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        await start(query, context)
    elif query.data == "dislocation":
        await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request":
        await query.edit_message_text("Введите номер контейнера для слежения:")

# --- Для inline-кнопки "дислокация" ---
async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

# --- Стикеры ---
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👍")

# --- Сообщения не относящиеся к командам ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, выберите команду из меню или используйте /start."
    )

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
    