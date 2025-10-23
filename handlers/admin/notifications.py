# handlers/admin/notifications.py (Добавьте эту функцию)
from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime, time
from services.notification_service import NotificationService 
from logger import get_logger

logger = get_logger(__name__)

async def force_notify_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Принудительный запуск рассылки уведомлений для текущего часа.
    Полностью повторяет логику job_send_notifications, но запускается по команде.
    """
    if update.effective_chat is None or update.effective_message is None:
        return
    
    # ❗ Рекомендуется: добавить проверку на админа, чтобы команда была доступна только вам.
    # Пример:
    # if update.effective_user.id != ADMIN_ID:
    #     await update.effective_message.reply_text("Эта команда доступна только администраторам.")
    #     return

    # 1. Определение целевого времени: текущий час в UTC.
    now_utc = datetime.utcnow()
    # Берем только час, минуты и секунды обнуляем, чтобы соответствовать notification_time в БД.
    target_time = time(hour=now_utc.hour, minute=0, second=0, microsecond=0)
    target_time_str = target_time.strftime('%H:%M')
    
    await update.effective_message.reply_text(
        f"⏳ Запуск принудительной рассылки для времени **{target_time_str}** (UTC)...",
        parse_mode="Markdown"
    )

    try:
        # 2. Инициализация и запуск сервиса
        service = NotificationService(context.bot)
        
        # Вызов основной логики рассылки из сервиса
        sent_count, total_count = await service.send_scheduled_notifications(target_time)

        final_message = (
            f"✅ **Принудительная рассылка завершена.**\n"
            f"Обработано подписок на время {target_time_str}: **{total_count}**\n"
            f"Отправлено сообщений: **{sent_count}**"
        )
        logger.info(f"[Force Notify] {final_message.replace('**', '')}")
        await update.effective_message.reply_text(final_message, parse_mode="Markdown")

    except Exception as e:
        error_message = f"❌ Критическая ошибка при принудительной рассылке для {target_time_str}: `{e}`"
        logger.critical(error_message, exc_info=True)
        await update.effective_message.reply_text(error_message, parse_mode="Markdown")