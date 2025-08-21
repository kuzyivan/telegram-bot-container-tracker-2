# handlers/menu_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from logger import get_logger
from utils.keyboards import reply_keyboard

logger = get_logger(__name__)

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text if update.message else ""
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        # Здесь просто выходим — дальнейшая логика в tracking_conversation_handler
        return
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        return await cancel_tracking_start(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.", reply_markup=reply_keyboard)

# --- Inline кнопки ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ВАЖНО: не вызываем start() из другого модуля, чтобы не плодить циклы импортов.
    Просто показываем соответствующие подсказки.
    """
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        # Покажем меню «в лоб»
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Выберите действие в меню:",
            reply_markup=reply_keyboard,
        )
    elif query.data == "dislocation":
        await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request":
        await query.edit_message_text("Введите номер контейнера для слежения:")

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")