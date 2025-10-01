# handlers/broadcast.py
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.error import BadRequest
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
    """Начинает диалог создания рассылки (адаптировано для кнопок)."""
    user = update.effective_user
    chat = update.effective_chat
    
    # Сразу проверяем наличие пользователя и чата
    if not user or not chat:
        return ConversationHandler.END

    if user.id != ADMIN_CHAT_ID:
        if update.message:
            await chat.send_message("⛔ Эта команда доступна только администратору.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END

    text = "Введите текст для рассылки всем пользователям:"
    
    # <<< НАЧАЛО ИЗМЕНЕНИЙ >>>
    # Если это нажатие кнопки, сначала отвечаем на него, чтобы убрать "часики"
    if update.callback_query:
        await update.callback_query.answer()

    # Универсально и безопасно отправляем новое сообщение в текущий чат
    await chat.send_message(text)
    # <<< КОНЕЦ ИЗМЕНЕНИЙ >>>
        
    return BROADCAST_TEXT


async def broadcast_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает текст рассылки и запрашивает подтверждение (безопасный предпросмотр)."""
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
    
    safe_text_preview = html.escape(text)
    
    await message.reply_text(
        f"<b>Текст для рассылки:</b>\n\n<pre>{safe_text_preview}</pre>\n\nОтправить это сообщение всем пользователям?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет рассылку с откатом на простой текст в случае ошибки парсинга."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    if query.data == "cancel_broadcast":
        await query.edit_message_text("Рассылка отменена.")
        return ConversationHandler.END

    if context.user_data is None:
        context.user_data = {}
    text = context.user_data.get('broadcast_text')
    if not text:
        await query.edit_message_text("Не найден текст для рассылки. Попробуйте снова.")
        return ConversationHandler.END

    user_ids = await get_all_user_ids()
    sent_count = 0
    failed_count = 0
    
    await query.edit_message_text(f"Начинаю рассылку для {len(user_ids)} пользователей...")

    for user_id in set(user_ids):
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')
            sent_count += 1
        except BadRequest as e:
            if "Can't parse entities" in str(e):
                logger.warning(f"Ошибка парсинга HTML для пользователя {user_id}. Пробую отправить как простой текст.")
                try:
                    await context.bot.send_message(chat_id=user_id, text=text)
                    sent_count += 1
                except Exception as plain_e:
                    failed_count += 1
                    logger.error(f"Не удалось отправить сообщение {user_id} даже как простой текст: {plain_e}")
            else:
                failed_count += 1
                logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        except Exception as e:
            failed_count += 1
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

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