# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from logger import get_logger

logger = get_logger(__name__)

# --- Главное меню ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # ИЗМЕНЕНИЕ: Обновляем клавиатуру, убирая устаревшие кнопки
    reply_keyboard = [
        ["📦 Дислокация"],
        ["/my_subscriptions - Мои подписки"],
    ]

    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚆\n\n"
        "Для поиска введите номер контейнера. Для управления подписками используйте команду /my_subscriptions.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )

    try:
        if update.effective_chat:
            await context.bot.send_sticker(
                chat_id=update.effective_chat.id,
                sticker="CAACAgIAAxkBAAJBOGiisUho8mpdezoAATaKIfwKypCNVgACb2wAAmvzmUhmDoR2oiG-5jYE"
            )
    except Exception:
        pass

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Эта функция теперь просто вызывает start для консистентности
    await start(update, context)

# --- Обработка reply-клавиатуры ---
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    # ИЗМЕНЕНИЕ: Направляем пользователя к новым командам
    elif text == "🔔 Задать слежение" or text == "❌ Отмена слежения":
        await update.message.reply_text(
            "Управление подписками теперь происходит через команду /my_subscriptions. Пожалуйста, используйте ее."
        )
    elif text == "/my_subscriptions - Мои подписки":
        # Импортируем здесь, чтобы избежать циклических зависимостей
        from .subscription_management_handler import my_subscriptions_command
        await my_subscriptions_command(update, context)
    else:
        # Передаем обработку текстовых сообщений (номеров контейнеров) в соответствующий хендлер
        from .dislocation_handlers import handle_message
        await handle_message(update, context)


# --- Обработка inline-кнопок (без изменений) ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if not update.callback_query:
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

# --- Обработка стикеров (без изменений) ---
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.message.sticker:
        return
    sticker = update.message.sticker
    logger.info(f"handle_sticker: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update, context)