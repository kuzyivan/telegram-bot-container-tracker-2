# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from logger import get_logger
from queries.user_queries import register_user # <<< ИЗМЕНЕНИЕ: Импортируем новую функцию

logger = get_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    
    # <<< ИЗМЕНЕНИЕ: Регистрируем пользователя при первом старте
    await register_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username
    )
    
    reply_keyboard = [
        ["📦 Дислокация"],
        ["📂 Мои подписки"],
    ]
    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚆\n\n"
        "Для поиска введите номер контейнера. Для управления подписками нажмите кнопку или используйте команду /my_subscriptions.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )
    try:
        if update.effective_chat:
            await context.bot.send_sticker(
                chat_id=update.effective_chat.id,
                sticker="CAACAgIAAxkBAAJBOGiisUho8mpdezoAATaKIfwKypCNVgACb2wAAmvzmUhmDoR2oiG-5jYE"
            )
    except Exception: pass

# ... (остальные функции остаются без изменений) ...
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "📂 Мои подписки":
        from handlers.subscription_management_handler import my_subscriptions_command
        await my_subscriptions_command(update, context)

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: return
    query = update.callback_query
    await query.answer()
    if query.data == "start": await show_menu(update, context)
    elif query.data == "dislocation": await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request": await query.edit_message_text("Введите номер контейнера для слежения:")

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.message.sticker: return
    sticker = update.message.sticker
    logger.info(f"Обработка стикера: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update, context)