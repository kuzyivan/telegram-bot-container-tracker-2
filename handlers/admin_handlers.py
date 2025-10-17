# handlers/admin_handlers.py
import pandas as pd
from datetime import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.helpers import escape_markdown
import os
from pathlib import Path

from config import ADMIN_CHAT_ID
from logger import get_logger
from utils.send_tracking import create_excel_file, create_excel_multisheet, get_vladivostok_filename
from utils.email_sender import send_email
from queries.admin_queries import (
    get_all_stats_for_export, get_all_tracking_subscriptions, get_daily_stats,
    get_data_for_test_notification, get_admin_user_for_email
)
from services.notification_service import NotificationService
from services.train_importer import import_train_from_excel, extract_train_code_from_filename
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_FOLDER as DISLOCATION_DOWNLOAD_FOLDER

logger = get_logger(__name__)

# Состояния для диалога /force_notify
AWAIT_FORCE_NOTIFY_TIME = range(1)

# --- Функции-проверки ---

def is_dislocation_file(filename: str) -> bool:
    """Проверяет, начинается ли имя файла с префикса '103_'."""
    return os.path.basename(filename).strip().startswith("103_")

async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, что команду вызвал администратор."""
    user = update.effective_user
    if not user:
        logger.warning("Отказ в доступе к админ-команде: отсутствует user.")
        return False
    if user.id != ADMIN_CHAT_ID:
        if update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, "⛔ Доступ запрещён.")
        logger.warning(f"Отказ в доступе к админ-команде пользователю {user.id}")
        return False
    return True

# --- Ручная загрузка файлов ---

async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инструкция по ручной загрузке файлов."""
    if not await admin_only_handler(update, context):
        return
    
    await update.message.reply_text(
        "Отправьте Excel-файл (.xlsx) для обновления данных:\n\n"
        "📄 **Файл дислокации**: Имя файла должно начинаться с `103_`.\n\n"
        "🚆 **Файл поезда**: Имя файла должно содержать номер вида `К25-073`.",
        parse_mode="Markdown"
    )

async def handle_admin_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый обработчик для Excel-файлов от администратора со строгими правилами и логированием."""
    if not await admin_only_handler(update, context) or not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = (doc.file_name or "unknown.xlsx").strip()
    
    if not filename.lower().endswith(".xlsx"):
        await update.message.reply_text("⛔ Пришлите, пожалуйста, Excel-файл в формате .xlsx")
        return

    os.makedirs(DISLOCATION_DOWNLOAD_FOLDER, exist_ok=True)
    dest_path = Path(DISLOCATION_DOWNLOAD_FOLDER) / filename
    
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(custom_path=str(dest_path))
    logger.info(f"📥 [Admin Upload] Получен файл от админа: {filename}. Сохранен как {dest_path}")

    try:
        # Этап 1: Проверка на "поезд"
        logger.info(f"[Admin Upload] Проверяю '{filename}' на соответствие файлу поезда...")
        if extract_train_code_from_filename(filename):
            logger.info(f"[Admin Upload] ✅ Успех. Файл '{filename}' определен как файл поезда.")
            updated, total, train_code = await import_train_from_excel(str(dest_path))
            text = (f"✅ Поезд <b>{train_code}</b> обработан.\n"
                    f"Обновлено контейнеров: <b>{updated}</b> из <b>{total}</b> в файле.")
            await update.message.reply_html(text)

        # Этап 2: Проверка на "дислокацию"
        elif is_dislocation_file(filename):
            logger.info(f"[Admin Upload] ✅ Успех. Файл '{filename}' определен как файл дислокации.")
            processed_count = await process_dislocation_file(str(dest_path))
            text = (f"✅ База дислокации успешно обновлена из файла.\n"
                    f"Обработано записей: <b>{processed_count}</b>.")
            await update.message.reply_html(text)

        # Этап 3: Отклонение
        else:
            logger.warning(f"[Admin Upload] ❗️ Отклонено. Файл '{filename}' не соответствует ни одному правилу.")
            await update.message.reply_markdown_v2(
                "❌ *Не удалось определить тип файла*\n\n"
                "Проверьте имя файла:\n"
                "• Для дислокации должно начинаться с `103_`\n"
                "• Для поезда должно содержать номер `К25\\-073`"
            )
            
    except Exception as e:
        logger.exception(f"[Admin Upload] 💥 КРИТИЧЕСКАЯ ОШИБКА при ручной обработке файла '{filename}'")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")

# --- Админ-панель ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_handler(update, context): return
    keyboard = [
        [InlineKeyboardButton("📊 Статистика за сутки", callback_data="admin_stats")],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data="admin_export_menu")],
        [InlineKeyboardButton("📢 Создать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚡️ Тестовое уведомление", callback_data="admin_testnotify")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message: await update.message.reply_text("⚙️ Панель администратора:", reply_markup=reply_markup)
    elif update.callback_query: await update.callback_query.edit_message_text("⚙️ Панель администратора:", reply_markup=reply_markup)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data: return
    await query.answer()
    action = query.data
    if action == "admin_stats": await stats(update, context)
    elif action == "admin_export_menu": await export_menu(update, context) # Добавим подменю
    elif action == "admin_testnotify": await test_notify(update, context)
    elif action == "admin_exportstats": await exportstats(update, context)
    elif action == "admin_tracking": await tracking(update, context)

# --- Экспорт данных ---

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
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    # ... (код функции без изменений)
    try:
        subs, columns = await get_all_tracking_subscriptions()
        # ...
    except Exception as e:
        # ...
        pass


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    # ... (код функции без изменений)
    try:
        rows = await get_daily_stats()
        # ...
    except Exception as e:
        # ...
        pass


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    # ... (код функции без изменений)
    try:
        rows, columns = await get_all_stats_for_export()
        # ...
    except Exception as e:
        # ...
        pass

# --- Уведомления ---

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    # ... (код функции без изменений)
    try:
        data_per_user = await get_data_for_test_notification()
        # ...
    except Exception as e:
        # ...
        pass


async def force_notify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код функции без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return ConversationHandler.END
    if context.args:
        return await _process_force_notify(update, context, context.args[0])
    await chat.send_message("Укажите время для рассылки (например, 09:00) или /cancel.")
    return AWAIT_FORCE_NOTIFY_TIME


async def force_notify_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код функции без изменений)
    if not update.message or not update.message.text: return ConversationHandler.END
    return await _process_force_notify(update, context, update.message.text.strip())


async def _process_force_notify(update: Update, context: ContextTypes.DEFAULT_TYPE, time_str: str):
    # ... (код функции без изменений)
    chat = update.effective_chat
    if not chat: return ConversationHandler.END
    try:
        # ...
        await service.send_scheduled_notifications(target_time)
        # ...
    except Exception as e:
        # ...
        pass
    return ConversationHandler.END


async def force_notify_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код функции без изменений)
    if update.message: await update.message.reply_text("Принудительная рассылка отменена.")
    return ConversationHandler.END

force_notify_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("force_notify", force_notify_start)],
    states={
        AWAIT_FORCE_NOTIFY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, force_notify_receive_time)],
    },
    fallbacks=[CommandHandler("cancel", force_notify_cancel)],
)