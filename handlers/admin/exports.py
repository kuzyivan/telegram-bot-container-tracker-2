# handlers/admin/exports.py
from telegram import Update
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
# ✅ ИСПРАВЛЕНИЕ: Используем существующий модуль для создания Excel-файлов
from utils.send_tracking import create_excel_file 
from utils.notify import notify_admin

logger = get_logger(__name__)

async def _send_stats_report(update: Update, context: ContextTypes.DEFAULT_TYPE, rows):
    """Форматирует и отправляет отчет о суточной статистике."""
    if not rows:
        await update.callback_query.edit_message_text("За последние 24 часа нет запросов (кроме запросов администратора).")
        return
        
    lines = ["📊 **Сводка запросов за 24 часа:**\n", 
             "| № | Юзер | Запр. | Контейнеры |", 
             "|---|---|---|---|"]
    
    for i, row in enumerate(rows):
        # row: (user_telegram_id, username, request_count, containers_str)
        user_id, username, count, containers = row
        # Обрезаем список контейнеров, чтобы поместиться в сообщение
        if len(containers) > 50:
             containers = containers[:47] + "..."
        
        lines.append(f"| {i+1} | {username} | {count} | {containers} |")
        
    # Разбиваем сообщение на части, так как оно может быть слишком большим
    response = "\n".join(lines)
    if len(response) > 4000:
         response = response[:4000] + "\n..."
         
    await update.callback_query.edit_message_text(response, parse_mode='Markdown')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats (статистика за 24 часа)."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    logger.info("[stats] Получен запрос на суточную статистику.")
    
    if update.callback_query:
        await update.callback_query.answer("Формирую отчет...")
    
    try:
        rows = await get_daily_stats() 
        if update.callback_query:
            await _send_stats_report(update, context, rows)
        else:
             # Если вызвано как команда, отправляем сообщение
             response = "Нет запросов за последние 24 часа (кроме администратора)."
             if rows:
                 response = "📊 Сводка запросов за 24 часа:\n"
                 for row in rows:
                     response += f"User {row[1]} ({row[0]}): {row[2]} запросов.\n"
             await update.message.reply_text(response)
             
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.edit_message_text(f"❌ Ошибка: Не удалось получить статистику. {e}")
        else:
            await update.message.reply_text(f"❌ Ошибка: Не удалось получить статистику.")

# --- Функции экспорта ---

async def _send_excel_export(update: Update, context: ContextTypes.DEFAULT_TYPE, rows, headers, filename_prefix: str):
    """Вспомогательная функция для генерации и отправки Excel."""
    file_path = None
    try:
        # ✅ ИСПРАВЛЕНИЕ: Используем create_excel_file
        file_path = await asyncio.to_thread(
            create_excel_file,
            rows,
            headers
        )
        
        await update.callback_query.edit_message_text(f"⏳ Экспорт {filename_prefix}...")

        with open(file_path, 'rb') as f:
            await update.callback_query.bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=f,
                filename=f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                caption=f"✅ Экспорт: {filename_prefix}"
            )
        await update.callback_query.edit_message_text(f"✅ Экспорт {filename_prefix} завершен и отправлен.")
        
    except Exception as e:
        logger.error(f"[Export] Ошибка экспорта {filename_prefix}: {e}", exc_info=True)
        await update.callback_query.edit_message_text(f"❌ Ошибка экспорта {filename_prefix}: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Коллбэк: Экспорт всех записей статистики (user_requests)."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.callback_query:
        return
    
    await update.callback_query.answer("Начинаю экспорт статистики...")
    
    try:
        rows, headers = await get_all_stats_for_export()
        if rows:
            await _send_excel_export(update, context, rows, headers, "user_requests_all")
        else:
             await update.callback_query.edit_message_text("Нет данных для экспорта статистики.")
             
    except Exception as e:
        logger.error(f"[Export] Критическая ошибка экспорта статистики: {e}", exc_info=True)
        await update.callback_query.edit_message_text(f"❌ Критическая ошибка экспорта статистики.")

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Коллбэк: Экспорт всех активных подписок (subscriptions)."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.callback_query:
        return
    
    await update.callback_query.answer("Начинаю экспорт подписок...")
    
    try:
        rows, headers = await get_all_tracking_subscriptions()
        if rows:
            await _send_excel_export(update, context, rows, headers, "subscriptions_all")
        else:
             await update.callback_query.edit_message_text("Нет данных для экспорта подписок.")
             
    except Exception as e:
        logger.error(f"[Export] Критическая ошибка экспорта подписок: {e}", exc_info=True)
        await update.callback_query.edit_message_text(f"❌ Критическая ошибка экспорта подписок.")