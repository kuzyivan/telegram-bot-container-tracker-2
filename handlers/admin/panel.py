# handlers/admin/panel.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from logger import get_logger
from .exports import stats, export_menu, tracking, exportstats # Добавляем импорты для колбэков
from .notifications import test_notify
from .utils import admin_only_handler # ✅ Импортируем из нового файла

logger = get_logger(__name__)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет основную панель администратора."""
    if not await admin_only_handler(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("📊 Статистика за сутки", callback_data="admin_stats")],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data="admin_export_menu")],
        [InlineKeyboardButton("📢 Создать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚡️ Тестовое уведомление", callback_data="admin_testnotify")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("⚙️ Панель администратора:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("⚙️ Панель администратора:", reply_markup=reply_markup)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок в панели администратора."""
    query = update.callback_query
    if not query or not query.data:
        return
        
    await query.answer()
    action = query.data

    if action == "admin_stats":
        await stats(update, context)
    elif action == "admin_export_menu":
        await export_menu(update, context)
    elif action == "admin_testnotify":
        await test_notify(update, context)
    elif action == "admin_panel_main":
        await admin_panel(update, context)
    # ✅ Добавляем обработку прямых экспортов из меню
    elif action == "admin_exportstats":
        await exportstats(update, context)
    elif action == "admin_tracking":
        await tracking(update, context)