from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.error import BadRequest
from utils.keyboards import (
    reply_keyboard,
    dislocation_inline_keyboard,
    tracking_inline_keyboard,
    main_menu_keyboard
)
import re
from models import Tracking, Stats
from db import (
    SessionLocal,
    get_all_user_ids,
    get_tracked_containers_by_user,
    remove_user_tracking,
    get_user
)
from sqlalchemy import select
from logger import get_logger

logger = get_logger(__name__)

# Стейты для ConversationHandler
SET_EMAIL = range(1)

# Регулярка для проверки email
EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$")

COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

# --- Команда /start ---
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

# --- Показать главное меню ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# --- Установка email через диалог ---
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

    if not EMAIL_REGEX.match(email):
        await update.message.reply_text("❌ Неверный формат email. Пожалуйста, попробуйте снова.")
        return SET_EMAIL

    async with SessionLocal() as session:
        user = await get_user(session, telegram_id)
        if user:
            user.username = username
            user.email = email
            user.email_enabled = True
            await session.commit()

            await update.message.reply_text(
                f"📬 Email <b>{email}</b> успешно сохранён, рассылка включена ✅",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("⚠️ Ошибка: пользователь не найден.")
    
    return ConversationHandler.END

async def cancel_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ввод email отменён.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Отключение email-уведомлений ---
async def email_off_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    async with SessionLocal() as session:
        user = await get_user(session, telegram_id)
        if user:
            user.email = None
            user.email_enabled = False
            await session.commit()
            await update.message.reply_text("📭 Email-уведомления отключены.")
        else:
            await update.message.reply_text("⚠️ Пользователь не найден.")

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        return
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        return await cancel_tracking_start(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.")

# --- Inline кнопки ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        await start(query, context)
    elif query.data == "dislocation":
        await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request":
        await query.edit_message_text("Введите номер контейнера для слежения:")

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

# --- Обработка стикеров ---
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    logger.info(f"handle_sticker: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')
    await show_menu(update, context)

# --- Вывод отслеживаемых контейнеров ---
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