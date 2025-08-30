from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from logger import get_logger
from config import ADMIN_CHAT_ID
from db import get_all_user_ids

logger = get_logger(__name__)

BROADCAST_TEXT, BROADCAST_CONFIRM = range(2)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог создания рассылки."""
    user = update.effective_user
    message = update.message
    if not user or not message:
        return ConversationHandler.END
    
    if user.id != ADMIN_CHAT_ID:
        await message.reply_text("⛔ Эта команда доступна только администратору.")
        return ConversationHandler.END
        
    await message.reply_text("Введите текст для рассылки всем пользователям:")
    return BROADCAST_TEXT

async def broadcast_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает текст рассылки и запрашивает подтверждение."""
    message = update.message
    if not message or not message.text:
        if message:
            await message.reply_text("Пожалуйста, отправьте текстовое сообщение.")
        return BROADCAST_TEXT

    text = message.text
    if context.user_data is None:
        context.user_data = {}
    context.user_data['broadcast_text'] = text
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Подтвердить и отправить", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")
        ]
    ])
    await message.reply_text(
        f"<b>Текст для рассылки:</b>\n\n{text}\n\nОтправить это сообщение всем пользователям?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет рассылку после подтверждения или отменяет ее."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    if query.data == "cancel_broadcast":
        # ИСПРАВЛЕНИЕ: Вызываем метод у объекта query
        await query.edit_message_text("Рассылка отменена.")
        return ConversationHandler.END

    if context.user_data is None:
        context.user_data = {}
    text = context.user_data.get('broadcast_text')
    if not text:
        # ИСПРАВЛЕНИЕ: Вызываем метод у объекта query
        await query.edit_message_text("Не найден текст для рассылки. Попробуйте снова.")
        return ConversationHandler.END

    user_ids = await get_all_user_ids()
    sent_count = 0
    failed_count = 0
    
    # ИСПРАВЛЕНИЕ: Вызываем метод у объекта query
    await query.edit_message_text(f"Начинаю рассылку для {len(user_ids)} пользователей...")

    for user_id in set(user_ids):
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')
            sent_count += 1
        except Exception as e:
            failed_count += 1
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    # ИСПРАВЛЕНИЕ: Вызываем метод у объекта query
    await query.edit_message_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно отправлено: {sent_count}\n"
        f"Не удалось отправить: {failed_count}"
    )
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отмену диалога рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")
    return ConversationHandler.END

broadcast_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={
        BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_get_text)],
        BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm)],
    },
    fallbacks=[CommandHandler("cancel", broadcast_cancel)],
)

