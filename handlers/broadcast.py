from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton

from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from logger import get_logger

logger = get_logger(__name__)

from config import ADMIN_CHAT_ID
from db import get_all_user_ids

BROADCAST_TEXT, BROADCAST_CONFIRM = range(2)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not user or not message:
        return ConversationHandler.END
    if user.id != ADMIN_CHAT_ID:
        await message.reply_text("Извини, только для админа.")
        return ConversationHandler.END
    await message.reply_text("Введи текст рассылки для всех пользователей:")
    return BROADCAST_TEXT

async def broadcast_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return ConversationHandler.END
    text = message.text
    if context.user_data is None:
        context.user_data = {}
    context.user_data['broadcast_text'] = text
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Подтвердить", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")
        ]
    ])
    await message.reply_text(
        f"Текст рассылки:\n\n{text}\n\nПодтвердить рассылку?",
        reply_markup=keyboard
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    if query.data == "cancel_broadcast":
        await query.edit_message_text("Рассылка отменена.")
        return ConversationHandler.END

    if context.user_data is None:
        context.user_data = {}
    text = context.user_data.get('broadcast_text', '')
    user_ids = await get_all_user_ids()
    sent_ids = []
    for user_id in set(user_ids):
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            sent_ids.append(user_id)
        except Exception:
            continue
    await query.edit_message_text(
        f"Рассылка завершена!\n"
        f"Успешно отправлено: {len(sent_ids)}\n"
        f"user_id: {', '.join(str(uid) for uid in sent_ids)}"
    )
    return ConversationHandler.END

broadcast_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={
        BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_get_text)],
        BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm)],
    },
    fallbacks=[],
)