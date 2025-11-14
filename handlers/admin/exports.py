# handlers/admin/exports.py
from telegram import Update, Message
from telegram.ext import ContextTypes
import asyncio
import os
from datetime import datetime

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.admin_queries import (
    get_daily_stats, 
    get_all_stats_for_export, 
    get_all_tracking_subscriptions, 
    get_data_for_test_notification, 
    get_admin_user_for_email
)
from utils.send_tracking import create_excel_file # Используем импорт для одного листа
from utils.telegram_text_utils import escape_markdown
from utils.notify import notify_admin

logger = get_logger(__name__)

async def _send_stats_report(update: Update, context: ContextTypes.DEFAULT_TYPE, rows):
    """Форматирует и отправляет отчет о суточной статистике."""
    # ... (логика форматирования отчета статистики остается прежней) ...
    if not rows: # Line 26
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text("За последние 24 часа нет запросов (кроме запросов администратора).") # Line 28
        elif update.message:
            await update.message.reply_text("За последние 24 часа нет запросов (кроме запросов администратора).")
        return
        
    lines = ["📊 **Сводка запросов за 24 часа:**\n", 
             "| № | Юзер | Запр. | Контейнеры |", 
             "|---|---|---|---|"]
    
    for i, row in enumerate(rows):
        user_id, username, count, containers = row
        # Escape user-generated content to prevent Markdown errors
        safe_username = escape_markdown(username or "N/A")
        safe_containers = escape_markdown(containers or "")

        if len(containers) > 50:
             safe_containers = escape_markdown(containers[:47] + "...")
        
        lines.append(f"| {i+1} | {safe_username} | {count} | {safe_containers} |")
        
    response = "\n".join(lines)
    if len(response) > 4000:
         response = response[:4000] + "\n..."
         
    if update.callback_query: # Simplified condition
        await update.callback_query.edit_message_text(response, parse_mode='Markdown') # Line 49
    elif update.message:
        await update.message.reply_text(response, parse_mode='Markdown')


# --- Функции экспорта ---

async def _send_excel_export(update: Update, context: ContextTypes.DEFAULT_TYPE, rows, headers, filename_prefix: str):
    """Вспомогательная функция для генерации и отправки Excel."""
    file_path = None
    try:
        if update.callback_query:
            await update.callback_query.answer("Начинаю экспорт...")
            # No need for isinstance(message, Message) here, call directly on query
            await update.callback_query.edit_message_text(f"⏳ Формирую Excel-файл для {filename_prefix}...") # Line 53
        elif update.message:
            await update.message.reply_text(f"⏳ Формирую Excel-файл для {filename_prefix}...")

        # Генерация файла
        file_path = await asyncio.to_thread(
            create_excel_file,
            rows,
            headers
        )
        
        # ✅ ИСПРАВЛЕНИЕ: Используем context.bot для отправки
        with open(file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=f,
                filename=f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                caption=f"✅ Экспорт: {filename_prefix}"
            )
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text(f"✅ Экспорт {filename_prefix} завершен и отправлен.") # Line 67
        elif update.message:
            await update.message.reply_text(f"✅ Экспорт {filename_prefix} завершен и отправлен.")
        
    except Exception as e:
        logger.error(f"[Export] Ошибка экспорта {filename_prefix}: {e}", exc_info=True)
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text(f"❌ Ошибка экспорта {filename_prefix}: {e}") # Line 75
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats (статистика за 24 часа)."""
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        return # Pylance fix: effective_user is checked here

    logger.info("[stats] Получен запрос на суточную статистику.")
    
    if update.callback_query:
        await update.callback_query.answer("Формирую отчет...")
    
    try:
        rows = await get_daily_stats() 
        if update.callback_query:
            await _send_stats_report(update, context, rows)
        else:
             response = "Нет запросов за последние 24 часа (кроме администратора)."
             if rows:
                 response = "📊 Сводка запросов за 24 часа:\n"
                 for row in rows:
                     response += f"User {row[1]} ({row[0]}): {row[2]} запросов.\n"
             if update.message: await update.message.reply_text(response) # Line 119

    except Exception as e: # Pylance fix: message is checked in _send_stats_report
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text(f"❌ Ошибка: Не удалось получить статистику. {e}") # Line 87
        elif update.message:
            await update.message.reply_text(f"❌ Ошибка: Не удалось получить статистику.")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Коллбэк: Экспорт всех записей статистики (user_requests)."""
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID or not update.callback_query: # Pylance fix: effective_user can be None
        return
    
    try:
        rows, headers = await get_all_stats_for_export()
        if rows and headers:
            # ✅ ИСПРАВЛЕНИЕ: Передаем headers
            await _send_excel_export(update, context, rows, headers, "user_requests_all") # Pylance fix: update.callback_query is checked in _send_excel_export
        elif update.callback_query: # Simplified condition
             await update.callback_query.edit_message_text("Нет данных для экспорта статистики.") # Line 94
             
    except Exception as e:
        logger.error(f"[Export] Критическая ошибка экспорта статистики: {e}", exc_info=True)
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text(f"❌ Критическая ошибка экспорта статистики.") # Line 124

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Коллбэк: Экспорт всех активных подписок (subscriptions)."""
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID or not update.callback_query: # Pylance fix: effective_user can be None
        return
    
    try:
        rows, headers = await get_all_tracking_subscriptions()
        if rows and headers:
            # ✅ ИСПРАВЛЕНИЕ: Передаем headers
            await _send_excel_export(update, context, rows, headers, "subscriptions_all") # Pylance fix: update.callback_query is checked in _send_excel_export
        elif update.callback_query: # Simplified condition
             await update.callback_query.edit_message_text("Нет данных для экспорта подписок.")
             
    except Exception as e:
        logger.error(f"[Export] Критическая ошибка экспорта подписок: {e}", exc_info=True)
        if update.callback_query: # Simplified condition
            await update.callback_query.edit_message_text(f"❌ Критическая ошибка экспорта подписок.")