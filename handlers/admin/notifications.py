# handlers/admin/notifications.py
from datetime import time
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

from .utils import admin_only_handler # ✅ ИЗМЕНЕНИЕ ЗДЕСЬ
from logger import get_logger
from utils.send_tracking import create_excel_multisheet, get_vladivostok_filename
from utils.email_sender import send_email
from queries.admin_queries import get_data_for_test_notification, get_admin_user_for_email
from config import ADMIN_CHAT_ID
from services.notification_service import NotificationService

logger = get_logger(__name__)
AWAIT_FORCE_NOTIFY_TIME = range(1)

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает тестовую рассылку на email администратора."""
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    
    try:
        await chat.send_message("⏳ Собираю данные для теста...")
        data_per_user = await get_data_for_test_notification()
        columns = ['Номер контейнера', 'Станция отправления', 'Станция назначения', 'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции']
        file_path = create_excel_multisheet(data_per_user, columns)
        filename = get_vladivostok_filename("Тестовая_дислокация")
        with open(file_path, "rb") as f:
            await chat.send_document(document=f, filename=filename)
        
        admin_user = await get_admin_user_for_email(ADMIN_CHAT_ID)
        if admin_user and admin_user.emails:
            email = admin_user.emails[0].email
            await send_email(to=email, attachments=[file_path])
            await chat.send_message(f"✅ Тестовый отчет отправлен на `{email}`.", parse_mode='Markdown')
        else:
            await chat.send_message("⚠️ Не найден email для тестовой отправки.")
    except Exception as e:
        logger.error(f"[test_notify] Ошибка: {e}", exc_info=True)
        if chat: await chat.send_message(f"❌ Ошибка: {e}")

async def force_notify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог принудительной рассылки."""
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context):
        return ConversationHandler.END
    
    if context.args:
        return await _process_force_notify(update, context, context.args[0])
    
    await chat.send_message("Укажите время для рассылки (например, 09:00) или /cancel.")
    return AWAIT_FORCE_NOTIFY_TIME

async def force_notify_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return ConversationHandler.END
    return await _process_force_notify(update, context, update.message.text.strip())

async def _process_force_notify(update: Update, context: ContextTypes.DEFAULT_TYPE, time_str: str):
    chat = update.effective_chat
    if not chat: return ConversationHandler.END
        
    try:
        hour, minute = map(int, time_str.split(':'))
        target_time = time(hour=hour, minute=minute)
    except ValueError:
        await chat.send_message("Неверный формат (ЧЧ:ММ). Попробуйте снова или /cancel.")
        return AWAIT_FORCE_NOTIFY_TIME

    await chat.send_message(f"🚀 Запускаю рассылку для {time_str}...")
    
    service = NotificationService(context.bot)
    try:
        await service.send_scheduled_notifications(target_time)
        await chat.send_message(f"✅ Рассылка для {time_str} завершена.")
    except Exception as e:
        logger.error(f"Ошибка при принудительной рассылке: {e}", exc_info=True)
        await chat.send_message(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

async def force_notify_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Отменено.")
    return ConversationHandler.END

force_notify_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("force_notify", force_notify_start)],
    states={
        AWAIT_FORCE_NOTIFY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, force_notify_receive_time)],
    },
    fallbacks=[CommandHandler("cancel", force_notify_cancel)],
)