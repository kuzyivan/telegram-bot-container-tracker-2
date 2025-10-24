# handlers/broadcast.py
import asyncio
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
)
from telegram.error import TelegramError

from logger import get_logger
# ✅ Исправляем импорт - берем функцию из user_queries
from queries.user_queries import get_all_user_ids 
from handlers.admin.utils import admin_only_handler # Используем проверку админа из utils

logger = get_logger(__name__)

# Состояния
AWAIT_BROADCAST_MESSAGE, CONFIRM_BROADCAST = range(2) # Добавляем состояние подтверждения

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог рассылки."""
    if not update.message or not await admin_only_handler(update, context):
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Введите сообщение для рассылки всем пользователям бота.\n"
        "Поддерживается MarkdownV2 (символы ., -, !, (, ) и др. нужно экранировать: `\\.`, `\\-` и т.д.).\n"
        "Используйте /cancel для отмены."
    )
    return AWAIT_BROADCAST_MESSAGE

async def broadcast_ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает сообщение, показывает предпросмотр и запрашивает подтверждение."""
    # ИСПРАВЛЕНИЕ: Удалена избыточная проверка "not context.user_data", которая приводила к завершению диалога.
    if not update.message or not update.message.text: 
        return ConversationHandler.END
    
    message_text = update.message.text
    # Используем MarkdownV2 для большей гибкости форматирования
    parse_mode = "MarkdownV2" 
    
    # Сохраняем текст сообщения для следующего шага
    context.user_data['broadcast_text'] = message_text
    context.user_data['broadcast_parse_mode'] = parse_mode

    # Показываем предпросмотр (экранируем для безопасности отображения в сообщении подтверждения)
    preview_text = message_text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("]", "\\]") \
                              .replace("(", "\\(").replace(")", "\\)").replace("~", "\\~").replace("`", "\\`") \
                              .replace(">", "\\>").replace("#", "\\#").replace("+", "\\+").replace("-", "\\-") \
                              .replace("=", "\\=").replace("|", "\\|").replace("{", "\\{").replace("}", "\\}") \
                              .replace(".", "\\.").replace("!", "\\!")

    await update.message.reply_text(
        f"Вы уверены, что хотите отправить следующее сообщение?\n\n---\n{preview_text}\n---\n\n"
        "Введите 'ДА' для подтверждения или /cancel для отмены.",
        parse_mode="MarkdownV2" # Отображаем сообщение подтверждения тоже с MarkdownV2
    )
    
    return CONFIRM_BROADCAST # Переходим в состояние подтверждения

async def broadcast_confirm_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждает и отправляет рассылку."""
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END

    confirmation = update.message.text.strip().upper()
    
    if confirmation != 'ДА':
        await update.message.reply_text("Отправка отменена.")
        context.user_data.clear()
        return ConversationHandler.END

    message_text = context.user_data.get('broadcast_text')
    parse_mode = context.user_data.get('broadcast_parse_mode')

    if not message_text:
         await update.message.reply_text("Ошибка: Текст сообщения потерян. Попробуйте /broadcast снова.")
         context.user_data.clear()
         return ConversationHandler.END

    await update.message.reply_text("Начинаю рассылку...")
    
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
            # logger.debug(f"Сообщение успешно отправлено пользователю {user_id}") # Можно раскомментировать для детального лога
            await asyncio.sleep(0.1) # Пауза между сообщениями (30 сообщений в секунду - лимит Telegram)
        except TelegramError as e:
            failed_sends += 1
            if "bot was blocked by the user" in str(e):
                 blocked_users +=1
                 logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: Бот заблокирован.")
                 # TODO: Возможно, стоит деактивировать пользователя или его подписки в базе
            else:
                 logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        except Exception as e:
             failed_sends += 1
             logger.error(f"Непредвиденная ошибка при отправке пользователю {user_id}: {e}", exc_info=True)

    logger.info(f"Рассылка завершена. Успешно: {successful_sends}, Ошибки: {failed_sends} (Заблокировано: {blocked_users})")
    await update.message.reply_text(
        f"Рассылка завершена.\n"
        f"✅ Успешно отправлено: {successful_sends}\n"
        f"❌ Ошибки: {failed_sends} (из них бот заблокирован: {blocked_users})"
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")
    if context.user_data: context.user_data.clear()
    return ConversationHandler.END

# Создаем ConversationHandler
broadcast_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={
        AWAIT_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_ask_confirm)], # Получаем текст
        CONFIRM_BROADCAST: [MessageHandler(filters.Regex('^ДА$'), broadcast_confirm_and_send)] # Ждем подтверждения 'ДА'
    },
    fallbacks=[CommandHandler("cancel", broadcast_cancel)],
)