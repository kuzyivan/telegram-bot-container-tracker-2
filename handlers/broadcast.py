# handlers/broadcast.py
import asyncio
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.error import BadRequest, Forbidden, ChatMigrated 
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from typing import cast, Dict, Any

from logger import get_logger
from config import ADMIN_CHAT_ID
# ✅ ИСПРАВЛЕНИЕ: Импортируем get_all_user_ids из queries.user_queries
from queries.user_queries import get_all_user_ids 

logger = get_logger(__name__)

BROADCAST_TEXT, BROADCAST_CONFIRM = range(2)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог создания рассылки."""
    user = update.effective_user
    chat = update.effective_chat
    
    if not user or not chat or user.id != ADMIN_CHAT_ID:
        if update.message:
            await chat.send_message("⛔ Эта команда доступна только администратору.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END

    logger.info(f"[/broadcast] Администратор {user.id} начал диалог рассылки.")

    # 🚨 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливаем маркер активности
    if context.user_data:
        context.user_data.pop('just_finished_conversation', None) # Удаляем маркер завершения, если остался
    else:
        context.user_data = {} # Создаем, если не существует
    context.user_data['is_broadcast_active'] = True

    # Используем Markdown для начального сообщения
    text = "📣 **Введите текст сообщения для рассылки всем пользователям бота.**\n\n" \
           "**Внимание!** Для сохранения пользовательских эмодзи форматирование HTML/Markdown будет отключено.\n" \
           "Используйте /cancel для отмены."
    
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
        
    # Приведение типа для Pylance
    user_data: Dict[str, Any] = cast(Dict[str, Any], context.user_data)
    
    user_data['broadcast_text'] = text
    
    logger.info(f"[/broadcast] Текст для рассылки получен и сохранен: {text[:50]}...")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Подтвердить и отправить", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")
        ]
    ])
    
    # ✅ ИСПОЛЬЗУЕМ HTML.ESCAPE И <pre> ДЛЯ БЕЗОПАСНОГО ПРЕДПРОСМОТРА
    # Это гарантирует, что вы видите символы, даже если они выглядят как HTML-теги.
    safe_text_preview = html.escape(text)
    
    await message.reply_text(
        f"<b>Текст для рассылки:</b>\n\n<pre>{safe_text_preview}</pre>\n\nОтправить это сообщение всем пользователям?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет рассылку БЕЗ parse_mode для сохранения кастомных эмодзи."""
    query = update.callback_query
    if not query or not query.message:
        if query: await query.answer("Сообщение недоступно.")
        return ConversationHandler.END
    await query.answer("Начинаю рассылку...")

    if query.data == "cancel_broadcast":
        await query.message.edit_text("❌ Рассылка отменена.")
        if context.user_data:
            context.user_data.pop('is_broadcast_active', None)
            context.user_data['just_finished_conversation'] = True
        return ConversationHandler.END

    # <<< НАЧАЛО ЛОГИКИ ОТПРАВКИ >>>
    user_data = context.user_data or {}
    text = user_data.get('broadcast_text')
    
    if not text:
        await query.message.edit_text("Не найден текст для рассылки. Попробуйте снова.")
        if context.user_data:
            context.user_data.pop('is_broadcast_active', None)
            context.user_data['just_finished_conversation'] = True
        return ConversationHandler.END

    user_ids = await get_all_user_ids()
    sent_count = 0
    failed_count = 0
    blocked_count = 0
    
    await query.message.edit_text(f"Начинаю рассылку для {len(user_ids)} пользователей...")
    logger.info(f"[BROADCAST_SEND] Начало рассылки сообщения для {len(user_ids)} пользователей.")

    for user_id in set(user_ids):
        try:
            # ✅ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: ОТПРАВКА БЕЗ parse_mode
            # Это сохранит кастомные эмодзи и предотвратит ошибку парсинга
            await context.bot.send_message(chat_id=user_id, text=text) 
            sent_count += 1
            await asyncio.sleep(0.1) 
        
        # Обработка ошибок Telegram API
        except Forbidden:
            blocked_count += 1
            failed_count += 1
            logger.warning(f"[BROADCAST_FAIL] Пользователь {user_id} заблокировал бота (Forbidden).")
        except BadRequest as e:
            error_str = str(e)
            if "Chat not found" in error_str or "User not found" in error_str:
                failed_count += 1
                logger.warning(f"[BROADCAST_FAIL] Чат/Пользователь {user_id} не найден.")
            else:
                failed_count += 1
                logger.warning(f"[BROADCAST_FAIL] Не удалось отправить сообщение {user_id}: {e}")
        except ChatMigrated as e:
            failed_count += 1
            logger.warning(f"[BROADCAST_WARN] Чат {user_id} мигрировал в {e.new_chat_id}. Пропуск.")
        except Exception as e:
            failed_count += 1
            logger.error(f"[BROADCAST_ERROR] Непредвиденная ошибка при отправке пользователю {user_id}: {e}", exc_info=True)


    logger.info(f"[BROADCAST_SEND] Рассылка завершена. Успешно: {sent_count}, Ошибки: {failed_count} (Заблокировано: {blocked_count})")
    
    await query.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно отправлено: {sent_count}\n"
        f"Не удалось отправить: {failed_count}\n"
        f"(Из них бот заблокирован: {blocked_count})"
    )

    if context.user_data:
        context.user_data.pop('is_broadcast_active', None) # Удаляем маркер активности
        context.user_data['just_finished_conversation'] = True # Устанавливаем маркер завершения

    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отмену диалога рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")

    if context.user_data:
        context.user_data.pop('is_broadcast_active', None) # Удаляем маркер активности
        context.user_data['just_finished_conversation'] = True # Устанавливаем маркер завершения

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
    name="broadcast_conversation",
)