# handlers/admin/exports.py
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from .utils import admin_only_handler # ✅ ИЗМЕНЕНИЕ ЗДЕСЬ
from logger import get_logger
from utils.send_tracking import create_excel_file
from utils.send_tracking import get_vladivostok_filename
from queries.admin_queries import (
    get_all_stats_for_export, get_all_tracking_subscriptions, get_daily_stats
)

logger = get_logger(__name__)

async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора типа экспорта."""
    query = update.callback_query
    if not query: return
    keyboard = [
        [InlineKeyboardButton("📤 Экспорт всей статистики", callback_data="admin_exportstats")],
        [InlineKeyboardButton("📂 Экспорт всех подписок", callback_data="admin_tracking")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel_main")]
    ]
    await query.edit_message_text("Выберите данные для экспорта:", reply_markup=InlineKeyboardMarkup(keyboard))

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует все подписки в Excel."""
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    
    try:
        subs, columns = await get_all_tracking_subscriptions()
        if not subs or not columns:
            await chat.send_message("Нет активных подписок.")
            return
        df = pd.DataFrame([list(row) for row in subs], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Подписки_на_трекинг")
        with open(file_path, "rb") as f:
            await chat.send_document(document=f, filename=filename)
    except Exception as e:
        logger.error(f"[tracking] Ошибка выгрузки подписок: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при экспорте.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет статистику использования за последние 24 часа."""
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    
    try:
        rows = await get_daily_stats()
        if not rows:
            await chat.send_message("Нет статистики за последние сутки.")
            return
        header = "📊 *Статистика за последние 24 часа:*\n\n"
        message = header
        for row in rows:
            safe_username = escape_markdown(str(row.username), version=2)
            safe_containers = escape_markdown(str(row.containers), version=2)
            entry = (f"👤 *{safe_username}* \\(ID: `{row.user_id}`\\)\n"
                     f"Запросов: *{row.request_count}*\n"
                     f"Контейнеры: `{safe_containers}`\n\n")
            if len(message) + len(entry) > 4000:
                await chat.send_message(message, parse_mode='MarkdownV2')
                message = entry
            else:
                message += entry
        if message != header:
            await chat.send_message(message, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при получении статистики.")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует всю статистику запросов в Excel."""
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    
    try:
        rows, columns = await get_all_stats_for_export()
        if not rows or not columns:
            await chat.send_message("Нет данных для экспорта.")
            return
        df = pd.DataFrame([list(row) for row in rows], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Статистика_запросов")
        with open(file_path, "rb") as f:
            await chat.send_document(document=f, filename=filename)
    except Exception as e:
        logger.error(f"[exportstats] Ошибка выгрузки статистики: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при экспорте.")