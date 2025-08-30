# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from logger import get_logger

from handlers.tracking_handlers import cancel_tracking_start

logger = get_logger(__name__)

# --- Главное меню ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что message существует
    if not update.message:
        return

    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]

    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚆\n"
        "Выберите действие в меню:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )

    try:
        # ИСПРАВЛЕНИЕ: Проверяем, что effective_chat существует
        if update.effective_chat:
            await context.bot.send_sticker(
                chat_id=update.effective_chat.id,
                sticker="CAACAgIAAxkBAAJBOGiisUho8mpdezoAATaKIfwKypCNVgACb2wAAmvzmUhmDoR2oiG-5jYE"
            )
    except Exception:
        pass

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]
    # ИСПРАВЛЕНИЕ: Проверяем, что effective_chat существует
    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Выберите действие в меню:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
        )

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что message и text существуют
    if not update.message or not update.message.text:
        return

    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        return
    elif text == "❌ Отмена слежения":
        await cancel_tracking_start(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.")

# --- Обработка inline-кнопок ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что callback_query существует
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    if query.data == "start":
        await show_menu(update, context)
    elif query.data == "dislocation":
        await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request":
        await query.edit_message_text("Введите номер контейнера для слежения:")

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что callback_query существует
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

# --- Обработка стикеров ---
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что message, user и sticker существуют
    if not update.message or not update.effective_user or not update.message.sticker:
        return

    sticker = update.message.sticker
    logger.info(f"handle_sticker: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update, context)