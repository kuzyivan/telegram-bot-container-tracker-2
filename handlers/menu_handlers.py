from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from logger import get_logger

from handlers.tracking_handlers import cancel_tracking_start

logger = get_logger(__name__)

# --- Главное меню ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]

    # приветствие + клавиатура
    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚆\n"
        "Выберите действие в меню:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )

    # стикер (не критичный, поэтому в try)
    try:
        await context.bot.send_sticker(
            chat_id=update.effective_chat.id,
            sticker="CAACAgIAAxkBAAJBOGiisUho8mpdezoAATaKIfwKypCNVgACb2wAAmvzmUhmDoR2oiG-5jYE"
        )
    except Exception:
        pass

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Унифицированный показ главного меню.
    Работает и для обычного сообщения, и когда его нет (например, из callback).
    """
    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Выберите действие в меню:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
        )

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        return  # Переход в трекинг-обработчик произойдет из main
    elif text == "❌ Отмена слежения":
        return await cancel_tracking_start(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.")

# --- Обработка inline-кнопок ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        # Показываем главное меню в чате, откуда пришёл callback
        await show_menu(update, context)
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
    await update.message.reply_text(f"🆔 ID этого стикера:\n{sticker.file_id}", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update, context)