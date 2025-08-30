# handlers/admin_handlers.py
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_CHAT_ID
from logger import get_logger
from utils.send_tracking import create_excel_file, create_excel_multisheet, get_vladivostok_filename
from utils.email_sender import send_email

# Импортируем наши новые функции для работы с БД
from queries.admin_queries import (
    get_all_stats_for_export,
    get_all_tracking_subscriptions,
    get_daily_stats,
    get_data_for_test_notification,
    get_admin_user_for_email,
)

logger = get_logger(__name__)


async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, является ли пользователь администратором. Возвращает True, если да."""
    if not update.message or not update.effective_user:
        logger.warning(f"Отказ в доступе к админ-команде: отсутствует message или user.")
        return False
    
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        logger.warning(f"Отказ в доступе к админ-команде пользователю {update.effective_user.id}")
        return False
    return True


async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message:
        return

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
        if update.message:
            await update.message.reply_text("❌ Ошибка при экспорте подписок.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message:
        return
    
    logger.info("[stats] Запрос статистики за сутки от администратора.")
    try:
        rows = await get_daily_stats()
        if not rows:
            await update.message.reply_text("Нет статистики за последние сутки.")
            return

        text_msg = "📊 **Статистика за последние 24 часа:**\n\n"
        for row in rows:
            entry = (
                f"👤 **{row.username}** (ID: `{row.user_id}`)\n"
                f"Запросов: **{row.request_count}**\n"
                f"Контейнеры: `{row.containers}`\n\n"
            )
            text_msg += entry
        
        await update.message.reply_text(text_msg, parse_mode='Markdown')
        logger.info("[stats] Статистика успешно отправлена.")
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Ошибка при получении статистики.")


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message:
        return

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
        if update.message:
            await update.message.reply_text("❌ Ошибка при экспорте статистики.")


async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context) or not update.message:
        return

    logger.info("[test_notify] Запрос тестовой мульти-рассылки от администратора.")
    try:
        data_per_user = await get_data_for_test_notification()
        columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ]
        
        file_path = create_excel_multisheet(data_per_user, columns)
        filename = get_vladivostok_filename("Тестовая_дислокация")

        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)
        await update.message.reply_text("✅ Тестовая мульти-рассылка готова.")

        admin_user = await get_admin_user_for_email(ADMIN_CHAT_ID)
        # ИСПРАВЛЕНИЕ: Используем явную проверку 'is not None'
        if admin_user and admin_user.email is not None:
            await send_email(to=admin_user.email, attachments=[file_path])
            logger.info(f"📧 Тестовое письмо отправлено на {admin_user.email}")

    except Exception as e:
        logger.error(f"[test_notify] Ошибка тестовой мульти-рассылки: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Ошибка при тестовой рассылке.")