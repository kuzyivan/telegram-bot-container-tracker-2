# handlers/broadcast.py
import asyncio
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.error import BadRequest, Forbidden, ChatMigrated # Добавлен Forbidden
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from logger import get_logger
from config import ADMIN_CHAT_ID
# ✅ ИСПРАВЛЕНИЕ: Импортируем get_all_user_ids из queries.user_queries, как в других файлах
from queries.user_queries import get_all_user_ids 

logger = get_logger(__name__)

BROADCAST_TEXT, BROADCAST_CONFIRM = range(2)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог создания рассылки."""
    user = update.effective_user
    chat = update.effective_chat
    
    if not user or not chat:
        return ConversationHandler.END

    # ✅ ИСПОЛЬЗУЕМ АДМИН-ПРОВЕРКУ (подразумевается, что она настроена)
    if user.id != ADMIN_CHAT_ID:
        if update.message:
            await chat.send_message("⛔ Эта команда доступна только администратору.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END

    # ✅ ИСПРАВЛЕНИЕ: Логирование начала команды
    logger.info(f"[/broadcast] Администратор {user.id} начал диалог рассылки.")

    text = "📣 **Введите текст сообщения для рассылки всем пользователям бота.**\n\n" \
           "Вы можете использовать форматирование HTML/Markdown. Для отмены введите /cancel"
    
    # Редактируем, если это был CallbackQuery, или отправляем новое сообщение
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.message:
            await update.callback_query.message.edit_text(text, parse_mode='Markdown')
        else:
             await chat.send_message(text, parse_mode='Markdown')
    else:
        await chat.send_message(text, parse_mode='Markdown')
        
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
    
    logger.info(f"[/broadcast] Текст для рассылки получен и сохранен: {text[:50]}...")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Подтвердить и отправить", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")
        ]
    ])
    
    # ✅ ИСПОЛЬЗУЕМ HTML ДЛЯ БЕЗОПАСНОГО ПРЕДПРОСМОТРА
    safe_text_preview = html.escape(text)
    
    await message.reply_text(
        f"<b>Текст для рассылки:</b>\n\n<pre>{safe_text_preview}</pre>\n\nОтправить это сообщение всем пользователям?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет рассылку с улучшенной диагностикой ошибок."""
    query = update.callback_query
    if not query or not query.message:
        return ConversationHandler.END
    await query.answer("Начинаю рассылку...")

    if query.data == "cancel_broadcast":
        await query.edit_message_text("❌ Рассылка отменена.")
        if context.user_data: context.user_data.clear()
        return ConversationHandler.END

    # <<< НАЧАЛО ЛОГИКИ ОТПРАВКИ >>>
    user_data = context.user_data or {}
    text = user_data.get('broadcast_text')
    
    if not text:
        await query.edit_message_text("Не найден текст для рассылки. Попробуйте снова.")
        if context.user_data: context.user_data.clear()
        return ConversationHandler.END

    # ✅ ИСПОЛЬЗУЕМ queries.user_queries.get_all_user_ids()
    user_ids = await get_all_user_ids()
    sent_count = 0
    failed_count = 0
    blocked_count = 0
    
    await query.edit_message_text(f"Начинаю рассылку для {len(user_ids)} пользователей...")
    logger.info(f"[BROADCAST_SEND] Начало рассылки сообщения для {len(user_ids)} пользователей.")

    for user_id in set(user_ids):
        try:
            # 1. Попытка отправить с HTML форматированием
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')
            sent_count += 1
            await asyncio.sleep(0.1) # Задержка для соблюдения лимитов Telegram
        
        # 2. Обработка распространенных ошибок Telegram API
        except Forbidden:
            # Пользователь заблокировал бота
            blocked_count += 1
            failed_count += 1
            logger.warning(f"[BROADCAST_FAIL] Пользователь {user_id} заблокировал бота (Forbidden).")
        except BadRequest as e:
            error_str = str(e)
            if "Chat not found" in error_str or "User not found" in error_str:
                # Чат/Пользователь не существует
                failed_count += 1
                logger.warning(f"[BROADCAST_FAIL] Чат/Пользователь {user_id} не найден (Chat not found/User not found).")
            elif "Can't parse entities" in error_str:
                # Ошибка форматирования HTML
                logger.warning(f"[BROADCAST_RETRY] Ошибка парсинга HTML для {user_id}. Пробую простой текст.")
                try:
                    await context.bot.send_message(chat_id=user_id, text=text)
                    sent_count += 1 # Считаем, что отправка прошла успешно
                except Exception as plain_e:
                    failed_count += 1
                    logger.error(f"[BROADCAST_FAIL] Не удалось отправить сообщение {user_id} даже как простой текст: {plain_e}")
            else:
                # Другие ошибки BadRequest (например, слишком длинный текст)
                failed_count += 1
                logger.warning(f"[BROADCAST_FAIL] Не удалось отправить сообщение {user_id}: {e}")
        except ChatMigrated as e:
            # Чат был мигрирован (редко)
            failed_count += 1
            logger.warning(f"[BROADCAST_WARN] Чат {user_id} мигрировал в {e.new_chat_id}. Пропуск.")
        except Exception as e:
            # Непредвиденные ошибки (сеть, таймаут и т.д.)
            failed_count += 1
            logger.error(f"[BROADCAST_ERROR] Непредвиденная ошибка при отправке пользователю {user_id}: {e}", exc_info=True)


    logger.info(f"[BROADCAST_SEND] Рассылка завершена. Успешно: {sent_count}, Ошибки: {failed_count} (Заблокировано: {blocked_count})")
    
    await query.edit_message_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно отправлено: {sent_count}\n"
        f"Не удалось отправить: {failed_count}\n"
        f"(Из них бот заблокирован: {blocked_count})"
    )
    
    if context.user_data: context.user_data.clear()
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отмену диалога рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")
    
    if context.user_data: context.user_data.clear()
    return ConversationHandler.END

# Главный ConversationHandler
broadcast_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("broadcast", broadcast_start),
        CallbackQueryHandler(broadcast_start, pattern="^admin_broadcast$")
    ],
    states={
        BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_get_text)],
        BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm)],
    },
    fallbacks=[CommandHandler("cancel", broadcast_cancel)],
)