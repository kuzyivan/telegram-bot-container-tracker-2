# handlers/admin_handlers.py
import pandas as pd
from datetime import time # <<< НОВОЕ: Импортируем time
from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from config import ADMIN_CHAT_ID
from logger import get_logger
from utils.send_tracking import create_excel_file, create_excel_multisheet, get_vladivostok_filename
from utils.email_sender import send_email
from queries.admin_queries import (
    get_all_stats_for_export,
    get_all_tracking_subscriptions,
    get_daily_stats,
    get_data_for_test_notification,
    get_admin_user_for_email,
)
# <<< НОВОЕ: Импортируем сервис уведомлений
from services.notification_service import NotificationService

logger = get_logger(__name__)


# ... (функции admin_only_handler, tracking, stats, exportstats, test_notify остаются без изменений) ...
async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        logger.warning(f"Отказ в доступе к админ-команде: отсутствует message или user.")
        return False
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        logger.warning(f"Отказ в доступе к админ-команде пользователю {update.effective_user.id}")
        return False
    return True

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message: return
    logger.info("[tracking] Запрос выгрузки всех подписок от администратора.")
    try:
        subs, columns = await get_all_tracking_subscriptions()
        if not subs or not columns:
            await update.message.reply_text("Нет активных слежений.")
            return
        df = pd.DataFrame([list(row) for row in subs], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Подписки_на_трекинг")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)
        logger.info("[tracking] Выгрузка подписок успешно отправлена.")
    except Exception as e:
        logger.error(f"[tracking] Ошибка выгрузки подписок: {e}", exc_info=True)
        if update.message: await update.message.reply_text("❌ Ошибка при экспорте подписок.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message: return
    logger.info("[stats] Запрос статистики за сутки от администратора.")
    try:
        rows = await get_daily_stats()
        if not rows:
            await update.message.reply_text("Нет статистики за последние сутки.")
            return
        TELEGRAM_MAX_LENGTH = 4000
        header = "📊 *Статистика за последние 24 часа:*\n"
        current_message = header
        for row in rows:
            safe_username = escape_markdown(str(row.username), version=2)
            safe_containers = escape_markdown(str(row.containers), version=2)
            entry = (f"👤 *{safe_username}* \\(ID: `{row.user_id}`\\)\n"
                     f"Запросов: *{row.request_count}*\n"
                     f"Контейнеры: `{safe_containers}`\n\n")
            if len(current_message) + len(entry) > TELEGRAM_MAX_LENGTH:
                await update.message.reply_text(current_message, parse_mode='MarkdownV2')
                current_message = header + entry
            else:
                current_message += entry
        if current_message != header:
            await update.message.reply_text(current_message, parse_mode='MarkdownV2')
        logger.info("[stats] Статистика успешно отправлена.")
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if update.message: await update.message.reply_text("❌ Ошибка при получении статистики.")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message: return
    logger.info("[exportstats] Запрос Excel-выгрузки всех запросов от администратора.")
    try:
        rows, columns = await get_all_stats_for_export()
        if not rows or not columns:
            await update.message.reply_text("Нет данных для экспорта.")
            return
        df = pd.DataFrame([list(row) for row in rows], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Статистика_запросов")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)
    except Exception as e:
        logger.error(f"[exportstats] Ошибка выгрузки статистики: {e}", exc_info=True)
        if update.message: await update.message.reply_text("❌ Ошибка при экспорте статистики.")

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message: return
    logger.info("[test_notify] Запрос тестовой мульти-рассылки от администратора.")
    try:
        data_per_user = await get_data_for_test_notification()
        columns = ['Номер контейнера', 'Станция отправления', 'Станция назначения', 'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции']
        file_path = create_excel_multisheet(data_per_user, columns)
        filename = get_vladivostok_filename("Тестовая_дислокация")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)
        await update.message.reply_text("✅ Тестовый Excel-отчет готов.")
        admin_user = await get_admin_user_for_email(ADMIN_CHAT_ID)
        if admin_user and admin_user.emails:
            first_email = admin_user.emails[0].email
            await send_email(to=first_email, attachments=[file_path])
            logger.info(f"📧 Тестовое письмо отправлено на {first_email}")
            await update.message.reply_text(f"📧 Тестовое письмо отправлено на `{first_email}`", parse_mode='Markdown')
        else:
            logger.warning(f"У администратора {ADMIN_CHAT_ID} нет сохраненных email для тестовой отправки.")
            await update.message.reply_text("⚠️ У вас нет сохраненных email для тестовой отправки.")
    except Exception as e:
        logger.error(f"[test_notify] Ошибка тестовой мульти-рассылки: {e}", exc_info=True)
        if update.message: await update.message.reply_text("❌ Ошибка при тестовой рассылке.")


# <<< НОВАЯ КОМАНДА ДЛЯ ТЕСТИРОВАНИЯ ---
async def force_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно запускает рассылку для указанного времени."""
    if not await admin_only_handler(update, context) or not update.message:
        return

    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите время для рассылки, например: /force_notify 09:00")
        return

    time_str = context.args[0]
    try:
        hour, minute = map(int, time_str.split(':'))
        target_time = time(hour=hour, minute=minute)
    except ValueError:
        await update.message.reply_text("Неверный формат времени. Используйте ЧЧ:ММ, например: /force_notify 09:00")
        return

    await update.message.reply_text(f"🚀 Принудительно запускаю рассылку для {time_str}...")
    
    service = NotificationService(context.bot)
    try:
        await service.send_scheduled_notifications(target_time)
        await update.message.reply_text(f"✅ Рассылка для {time_str} завершена. Проверяйте результат.")
        logger.info(f"[force_notify] Админ принудительно запустил и завершил рассылку для {time_str}")
    except Exception as e:
        logger.error(f"[force_notify] Ошибка при принудительной рассылке: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Во время принудительной рассылки произошла ошибка. См. логи.")