# handlers/broadcast.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
from telegram.error import TelegramError
from typing import cast, Dict, Any

from logger import get_logger
from queries.user_queries import get_all_user_ids 
from handlers.admin.utils import admin_only_handler
from config import ADMIN_CHAT_ID 
# ✅ ИМПОРТИРУЕМ ФУНКЦИЮ ДЛЯ КЛАВИАТУРЫ ИЗ UTILS/KEYBOARDS.PY
from utils.keyboards import create_broadcast_confirm_keyboard

logger = get_logger(__name__)

# Состояния
AWAIT_BROADCAST_MESSAGE, CONFIRM_BROADCAST = range(2) 

# --- Обработчики ConversationHandler ---

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог рассылки."""
    # Строки 40, 50, 51: Проверка на update.message и admin_only_handler гарантирует, 
    # что мы работаем с реальным сообщением от админа.
    if not update.message or not await admin_only_handler(update, context):
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Введите сообщение для рассылки всем пользователям бота.\n"
        "Поддерживается MarkdownV2 (символы ., -, !, (, ) и др. нужно экранировать: `\\.`, `\\-` и т.д.).\n"
        "Используйте /cancel для отмены."
    )
    return AWAIT_BROADCAST_MESSAGE

async def broadcast_ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Получает сообщение, показывает предпросмотр и запрашивает подтверждение
    с помощью инлайн-кнопок.
    """
    # Дополнительная проверка для Pylance
    if not update.message or not update.message.text or not update.effective_user: 
        logger.warning("[BROADCAST_ASK] Message, text or user is missing. Ending conversation.")
        return ConversationHandler.END

    logger.info(f"[BROADCAST_ASK] Получен текст от {update.effective_user.id}: {update.message.text[:50]}...")
    
    # Приведение типа, чтобы Pylance не жаловался на context.user_data
    user_data: Dict[str, Any] = cast(Dict[str, Any], context.user_data)
    
    message_text = update.message.text
    parse_mode = "MarkdownV2" 
    
    user_data['broadcast_text'] = message_text
    user_data['broadcast_parse_mode'] = parse_mode

    # Показываем предпросмотр (агрессивное экранирование спецсимволов)
    preview_text = message_text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("]", "\\]") \
                              .replace("(", "\\(").replace(")", "\\)").replace("~", "\\~").replace("`", "\\`") \
                              .replace(">", "\\>").replace("#", "\\#").replace("+", "\\+").replace("-", "\\-") \
                              .replace("=", "\\=").replace("|", "\\|").replace("{", "\\{").replace("}", "\\}") \
                              .replace(".", "\\.").replace("!", "\\!")
    
    # Форматируем сообщение подтверждения с экранированием обрамляющего текста
    confirmation_text = (
        f"📣 **Предпросмотр рассылки**\n"
        f"Вы уверены, что хотите отправить следующее сообщение всем пользователям\\?\n"
        f"\n\\-\\-\\-\n"
        f"{preview_text}\n"
        f"\\-\\-\\-\n"
    )

    await update.message.reply_text(
        confirmation_text,
        reply_markup=create_broadcast_confirm_keyboard(),
        parse_mode="MarkdownV2"
    )
    
    return CONFIRM_BROADCAST 

async def broadcast_confirm_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ввод 'ДА' (на случай, если пользователь введет его текстом)."""
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END

    confirmation = update.message.text.strip().upper()
    
    if confirmation != 'ДА':
        await update.message.reply_text("Отправка отменена.")
        context.user_data.clear()
        return ConversationHandler.END

    # Если сработало, запускаем логику отправки
    return await _execute_broadcast_logic(update.message, context)


async def _execute_broadcast_logic(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отдельная функция, выполняющая рассылку."""
    
    # Строки 97, 98: Добавлены безопасные .get() и проверка context.user_data
    if context.user_data is None:
        return ConversationHandler.END
        
    message_text = context.user_data.get('broadcast_text')
    parse_mode = context.user_data.get('broadcast_parse_mode')

    if not message_text:
         await message.reply_text("Ошибка: Текст сообщения потерян. Попробуйте /broadcast снова.")
         context.user_data.clear()
         return ConversationHandler.END

    await message.reply_text("Начинаю рассылку...")
    
    user_ids = await get_all_user_ids()
    successful_sends = 0
    failed_sends = 0
    blocked_users = 0
    
    logger.info(f"Начало рассылки сообщения для {len(user_ids)} пользователей.")

    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode=parse_mode
            )
            successful_sends += 1
            await asyncio.sleep(0.1) # Пауза между сообщениями
        except TelegramError as e:
            failed_sends += 1
            if "bot was blocked by the user" in str(e):
                 blocked_users +=1
                 logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: Бот заблокирован.")
            else:
                 logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        except Exception as e:
             failed_sends += 1
             logger.error(f"Непредвиденная ошибка при отправке пользователю {user_id}: {e}", exc_info=True)

    logger.info(f"Рассылка завершена. Успешно: {successful_sends}, Ошибки: {failed_sends} (Заблокировано: {blocked_users})")
    await message.reply_text(
        f"Рассылка завершена.\n"
        f"✅ Успешно отправлено: {successful_sends}\n"
        f"❌ Ошибки: {failed_sends} (из них бот заблокирован: {blocked_users})"
    )
    
    # Строка 103: Добавлена проверка context.user_data
    if context.user_data is not None:
        context.user_data.clear()
        
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")
    
    # Строка 143: Добавлена проверка context.user_data
    if context.user_data is not None: 
        context.user_data.clear()
        
    return ConversationHandler.END


# --- ХЕНДЛЕР для обработки нажатия Inline-кнопок ---

async def handle_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает нажатия кнопок Подтвердить/Отменить на шаге CONFIRM_BROADCAST."""
    query = update.callback_query
    
    # Проверка query и from_user
    if not query or not query.data or not query.from_user or query.from_user.id != ADMIN_CHAT_ID:
        if query: await query.answer("Действие недоступно.")
        return CONFIRM_BROADCAST

    # Строка 160: Проверка на query гарантирует, что answer будет вызван
    await query.answer()

    if query.data == 'broadcast_confirm_yes':
        # Отправляем новое сообщение и очищаем кнопки в старом.
        if query.message:
            # Строки 167, 171: Добавлена проверка query.message
            await context.bot.send_message(
                query.message.chat_id, 
                "✅ **Подтверждено**. Запуск рассылки...", 
                parse_mode='Markdown'
            )
            await query.message.edit_reply_markup(reply_markup=None)
            
        return await _execute_broadcast_logic(query.message, context)
        
    elif query.data == 'broadcast_confirm_no':
        # Отправляем новое сообщение об отмене, а старое только очищаем
        if query.message:
            # Строки 178, 179: Добавлена проверка query.message
            await query.message.edit_reply_markup(reply_markup=None)
            await context.bot.send_message(
                query.message.chat_id, 
                "❌ **Отправка отменена.**", 
                parse_mode='Markdown'
            )
            
        if context.user_data: context.user_data.clear()
        return ConversationHandler.END
        
    return CONFIRM_BROADCAST


# Создаем ConversationHandler
broadcast_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={
        AWAIT_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_ask_confirm)],
        CONFIRM_BROADCAST: [
            # Обработчик для колбэков
            CallbackQueryHandler(handle_broadcast_callback, pattern="^broadcast_confirm_"),
            # Обработчик для прямого ввода 'ДА'
            MessageHandler(filters.Regex('^ДА$'), broadcast_confirm_and_send)
        ]
    },
    fallbacks=[CommandHandler("cancel", broadcast_cancel)],
)