# handlers/misc_handlers.py
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from utils.keyboards import reply_keyboard
from db import get_tracked_containers_by_user, remove_user_tracking
from logger import get_logger

logger = get_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Приветствие + вывод главного меню.
    Важно: эта функция должна вызываться ТОЛЬКО из апдейта с message.
    """
    chat_id = update.effective_chat.id if update.effective_chat else None
    logger.info(f"[start] chat_id={chat_id}")

    # На всякий случай: если пришёл callback_query, просто отправим новое сообщение с меню
    if update.callback_query:
        await update.callback_query.answer()
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Привет! Я бот для отслеживания контейнеров 🚆\nВыберите действие в меню:",
                reply_markup=reply_keyboard
            )
        return

    # Обычный кейс: апдейт с message
    if update.message:
        await update.message.reply_text(
            "Привет! Я бот для отслеживания контейнеров 🚆\nВыберите действие в меню:",
            reply_markup=reply_keyboard,
        )
        # Стикер (как было)
        await context.bot.send_sticker(
            chat_id=update.effective_chat.id,
            sticker="CAACAgIAAxkBAAJBOGiisUho8mpdezoAATaKIfwKypCNVgACb2wAAmvzmUhmDoR2oiG-5jYE"
        )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Переотображение главного меню.
    """
    chat_id = update.effective_chat.id if update.effective_chat else None
    logger.info(f"[show_menu] chat_id={chat_id}")

    if update.callback_query:
        await update.callback_query.answer()
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Выберите действие в меню:",
                reply_markup=reply_keyboard
            )
        return

    if update.message:
        await update.message.reply_text("Выберите действие в меню:", reply_markup=reply_keyboard)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ответ на стикер: показать его file_id и вернуть пользователя в меню.
    """
    if not update.message or not update.message.sticker:
        return

    sticker = update.message.sticker
    user_id = update.effective_user.id if update.effective_user else "—"
    logger.info(f"[handle_sticker] user={user_id}, sticker_id={sticker.file_id}")

    # В Markdown в старом коде была обратная кавычка; здесь используем MarkdownV2‑безопасность
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update, context)

async def show_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показать контейнеры пользователя, которые стоят на слежении.
    """
    user_id = update.message.from_user.id if update.message else (update.effective_user.id if update.effective_user else None)
    if not user_id:
        return
    containers = await get_tracked_containers_by_user(user_id)
    if containers:
        msg = "Вы отслеживаете контейнеры:\n" + "\n".join(containers)
    else:
        msg = "У вас нет активных подписок на контейнеры."
    await update.message.reply_text(msg)

async def cancel_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Снять все подписки пользователя.
    """
    user_id = update.message.from_user.id if update.message else (update.effective_user.id if update.effective_user else None)
    if not user_id:
        return
    await remove_user_tracking(user_id)
    await update.message.reply_text("Все подписки успешно отменены.", reply_markup=ReplyKeyboardRemove())
    await show_menu(update, context)