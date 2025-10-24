# handlers/broadcast.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
from telegram.error import TelegramError

from logger import get_logger
from queries.user_queries import get_all_user_ids 
from handlers.admin.utils import admin_only_handler
from config import ADMIN_CHAT_ID # Используем для фильтра колбэков

logger = get_logger(__name__)

# Состояния
AWAIT_BROADCAST_MESSAGE, CONFIRM_BROADCAST = range(2) 

# --- Вспомогательная функция для UX (в идеале должна быть в utils/keyboards.py) ---

def create_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Создает Inline клавиатуру для подтверждения рассылки."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="broadcast_confirm_yes"),
            InlineKeyboardButton("❌ Отменить", callback_data="broadcast_confirm_no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Обработчики ConversationHandler ---

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
    """
    Получает сообщение, показывает предпросмотр и запрашивает подтверждение
    с помощью инлайн-кнопок.
    """
    logger.info(f"[BROADCAST_ASK] Получен текст от {update.effective_user.id}: {update.message.text[:50]}...")
    
    if not update.message or not update.message.text: 
        logger.warning("[BROADCAST_ASK] Message or text is missing. Ending conversation.")
        return ConversationHandler.END
    
    message_text = update.message.text
    parse_mode = "MarkdownV2" 
    
    context.user_data['broadcast_text'] = message_text
    context.user_data['broadcast_parse_mode'] = parse_mode

    # Показываем предпросмотр
    # Агрессивное экранирование спецсимволов, чтобы они не ломали форматирование сообщения подтверждения.
    # Это CRITICAL FIX из предыдущего шага.
    preview_text = message_text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("]", "\\]") \
                              .replace("(", "\\(").replace(")", "\\)").replace("~", "\\~").replace("`", "\\`") \
                              .replace(">", "\\>").replace("#", "\\#").replace("+", "\\+").replace("-", "\\-") \
                              .replace("=", "\\=").replace("|", "\\|").replace("{", "\\{").replace("}", "\\}") \
                              .replace(".", "\\.").replace("!", "\\!")
    
    # ИСПРАВЛЕНИЕ UX: Форматируем сообщение подтверждения
    
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
    
    return CONFIRM_BROADCAST # Переходим в состояние подтверждения

async def broadcast_confirm_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждает и отправляет рассылку (логика остается, но вызывается колбэком)."""
    # Этот обработчик теперь должен вызываться ТОЛЬКО через callback_query, но мы его оставим 
    # для обработки прямого ввода 'ДА', если пользователь его отправит.
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END

    confirmation = update.message.text.strip().upper()
    
    if confirmation != 'ДА':
        await update.message.reply_text("Отправка отменена.")
        context.user_data.clear()
        return ConversationHandler.END

    # Если сработал Regex на 'ДА', то переходим к отправке
    return await _execute_broadcast_logic(update.message, context)


async def _execute_broadcast_logic(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отдельная функция, выполняющая рассылку."""
    
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
    
    context.user_data.clear()
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог рассылки."""
    if update.message:
        await update.message.reply_text("Рассылка отменена.")
    if context.user_data: context.user_data.clear()
    return ConversationHandler.END


# --- НОВЫЙ ХЕНДЛЕР для обработки нажатия Inline-кнопок ---

async def handle_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает нажатия кнопок Подтвердить/Отменить на шаге CONFIRM_BROADCAST."""
    query = update.callback_query
    if not query or not query.data or not query.from_user or query.from_user.id != ADMIN_CHAT_ID:
        # Проверяем, что это админ, чтобы избежать ошибок с чужими колбэками
        await query.answer("Действие недоступно.")
        return CONFIRM_BROVERATION

    await query.answer()

    if query.data == 'broadcast_confirm_yes':
        # Редактируем сообщение, чтобы убрать кнопки и показать, что начата работа
        if query.message:
             await query.message.edit_text(query.message.text + "\n\n**Запуск рассылки...**", parse_mode='MarkdownV2')
        return await _execute_broadcast_logic(query.message, context)
        
    elif query.data == 'broadcast_confirm_no':
        if query.message:
            await query.message.edit_text(query.message.text + "\n\n❌ **Отправка отменена.**", parse_mode='MarkdownV2')
        if context.user_data: context.user_data.clear()
        return ConversationHandler.END
        
    return CONFIRM_BROADCAST


# Создаем ConversationHandler
broadcast_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_start)],
    states={
        AWAIT_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_ask_confirm)],
        CONFIRM_BROADCAST: [
            # Добавляем обработчик для колбэков
            CallbackQueryHandler(handle_broadcast_callback, pattern="^broadcast_confirm_"),
            # Оставляем старый обработчик на случай, если пользователь введет "ДА" текстом
            MessageHandler(filters.Regex('^ДА$'), broadcast_confirm_and_send)
        ]
    },
    fallbacks=[CommandHandler("cancel", broadcast_cancel)],
)