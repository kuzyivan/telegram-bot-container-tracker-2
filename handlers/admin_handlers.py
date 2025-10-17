# handlers/admin_handlers.py
import pandas as pd
from datetime import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
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
# ✅ Новые импорты для обработки файлов
from services.train_importer import import_train_from_excel, extract_train_code_from_filename
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_FOLDER as DISLOCATION_DOWNLOAD_FOLDER

logger = get_logger(__name__)

# --- НОВЫЙ ФУНКЦИОНАЛ: РУЧНАЯ ЗАГРУЗКА ФАЙЛОВ ---

async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инструкция по ручной загрузке файлов."""
    if not await admin_only_handler(update, context):
        return
    
    await update.message.reply_text(
        "Отправьте Excel-файл (.xlsx) для обновления данных:\n\n"
        "📄 **Файл дислокации**: Просто отправьте файл, бот обновит данные по всем контейнерам в нем.\n\n"
        "🚆 **Файл поезда**: Название файла должно содержать номер поезда в формате `К25-073` (например, 'КП К25-073 Селятино.xlsx'). Бот проставит этот номер поезда всем контейнерам из файла.",
        parse_mode="Markdown"
    )

async def handle_admin_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый обработчик для Excel-файлов от администратора."""
    if not await admin_only_handler(update, context) or not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = (doc.file_name or "unknown.xlsx").strip()
    
    if not filename.lower().endswith(".xlsx"):
        await update.message.reply_text("⛔ Пришлите, пожалуйста, Excel-файл в формате .xlsx")
        return

    # Убедимся, что папка для загрузки существует
    os.makedirs(DISLOCATION_DOWNLOAD_FOLDER, exist_ok=True)
    dest_path = Path(DISLOCATION_DOWNLOAD_FOLDER) / filename
    
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(custom_path=str(dest_path))
    logger.info(f"📥 Получен файл от админа: {dest_path}")

    # Определяем тип файла и обрабатываем
    try:
        if extract_train_code_from_filename(filename):
            # --- Логика для файла поезда ---
            logger.info(f"Файл '{filename}' определен как файл поезда. Запуск импорта поезда...")
            updated, total, train_code = await import_train_from_excel(str(dest_path))
            text = (
                f"✅ Поезд <b>{train_code}</b> обработан.\n"
                f"Обновлено контейнеров: <b>{updated}</b> из <b>{total}</b> в файле."
            )
            await update.message.reply_html(text)
        else:
            # --- Логика для файла дислокации ---
            logger.info(f"Файл '{filename}' определен как файл дислокации. Запуск обновления базы...")
            processed_count = await process_dislocation_file(str(dest_path))
            text = (
                f"✅ База дислокации успешно обновлена из файла.\n"
                f"Обработано записей: <b>{processed_count}</b>."
            )
            await update.message.reply_html(text)
    except Exception as e:
        logger.exception(f"Ошибка при ручной обработке файла '{filename}'")
        await update.message.reply_text(f"❌ Произошла ошибка при обработке файла: {e}")


# --- СТАРЫЙ ФУНКЦИОНАЛ (без изменений) ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    if not await admin_only_handler(update, context): return
    keyboard = [[InlineKeyboardButton("📊 Статистика за сутки", callback_data="admin_stats")], [InlineKeyboardButton("📤 Экспорт всей статистики", callback_data="admin_exportstats")], [InlineKeyboardButton("📂 Экспорт всех подписок", callback_data="admin_tracking")], [InlineKeyboardButton("📢 Создать рассылку", callback_data="admin_broadcast")], [InlineKeyboardButton("⚡️ Тестовое уведомление", callback_data="admin_testnotify")],]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message: await update.message.reply_text("⚙️ Панель администратора:", reply_markup=reply_markup)
    elif update.callback_query: await update.callback_query.edit_message_text("⚙️ Панель администратора:", reply_markup=reply_markup)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    query = update.callback_query
    if not query: return
    await query.answer()
    action = query.data
    if action == "admin_stats": await stats(update, context)
    elif action == "admin_exportstats": await exportstats(update, context)
    elif action == "admin_tracking": await tracking(update, context)
    elif action == "admin_testnotify": await test_notify(update, context)

async def admin_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ... (код без изменений)
    user = update.effective_user
    if not user: logger.warning("Отказ в доступе к админ-команде: отсутствует user."); return False
    if user.id != ADMIN_CHAT_ID:
        if update.effective_chat: await context.bot.send_message(update.effective_chat.id, "⛔ Доступ запрещён.")
        logger.warning(f"Отказ в доступе к админ-команде пользователю {user.id}"); return False
    return True

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    logger.info("[tracking] Запрос выгрузки всех подписок от администратора.")
    try:
        subs, columns = await get_all_tracking_subscriptions()
        if not subs or not columns: await chat.send_message("Нет активных слежений."); return
        df = pd.DataFrame([list(row) for row in subs], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Подписки_на_трекинг")
        with open(file_path, "rb") as f: await chat.send_document(document=f, filename=filename)
        logger.info("[tracking] Выгрузка подписок успешно отправлена.")
    except Exception as e:
        logger.error(f"[tracking] Ошибка выгрузки подписок: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при экспорте подписок.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    logger.info("[stats] Запрос статистики за сутки от администратора.")
    try:
        rows = await get_daily_stats()
        if not rows: await chat.send_message("Нет статистики за последние сутки."); return
        TELEGRAM_MAX_LENGTH = 4000
        header = "📊 *Статистика за последние 24 часа:*\n"
        current_message = header
        for row in rows:
            safe_username = escape_markdown(str(row.username), version=2)
            safe_containers = escape_markdown(str(row.containers), version=2)
            entry = (f"👤 *{safe_username}* \\(ID: `{row.user_id}`\\)\nЗапросов: *{row.request_count}*\nКонтейнеры: `{safe_containers}`\n\n")
            if len(current_message) + len(entry) > TELEGRAM_MAX_LENGTH:
                await chat.send_message(current_message, parse_mode='MarkdownV2'); current_message = header + entry
            else: current_message += entry
        if current_message != header: await chat.send_message(current_message, parse_mode='MarkdownV2')
        logger.info("[stats] Статистика успешно отправлена.")
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при получении статистики.")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    logger.info("[exportstats] Запрос Excel-выгрузки всех запросов от администратора.")
    try:
        rows, columns = await get_all_stats_for_export()
        if not rows or not columns: await chat.send_message("Нет данных для экспорта."); return
        df = pd.DataFrame([list(row) for row in rows], columns=columns)
        file_path = create_excel_file(df.values.tolist(), df.columns.tolist())
        filename = get_vladivostok_filename("Статистика_запросов")
        with open(file_path, "rb") as f: await chat.send_document(document=f, filename=filename)
    except Exception as e:
        logger.error(f"[exportstats] Ошибка выгрузки статистики: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при экспорте статистики.")

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    logger.info("[test_notify] Запрос тестовой мульти-рассылки от администратора.")
    try:
        data_per_user = await get_data_for_test_notification()
        columns = ['Номер контейнера', 'Станция отправления', 'Станция назначения', 'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции']
        file_path = create_excel_multisheet(data_per_user, columns)
        filename = get_vladivostok_filename("Тестовая_дислокация")
        with open(file_path, "rb") as f: await chat.send_document(document=f, filename=filename)
        await chat.send_message("✅ Тестовый Excel-отчет готов.")
        admin_user = await get_admin_user_for_email(ADMIN_CHAT_ID)
        if admin_user and admin_user.emails:
            first_email = admin_user.emails[0].email
            await send_email(to=first_email, attachments=[file_path])
            logger.info(f"📧 Тестовое письмо отправлено на {first_email}")
            await chat.send_message(f"📧 Тестовое письмо отправлено на `{first_email}`", parse_mode='Markdown')
        else:
            logger.warning(f"У администратора {ADMIN_CHAT_ID} нет сохраненных email для тестовой отправки.")
            await chat.send_message("⚠️ У вас нет сохраненных email для тестовой отправки.")
    except Exception as e:
        logger.error(f"[test_notify] Ошибка тестовой мульти-рассылки: {e}", exc_info=True)
        if chat: await chat.send_message("❌ Ошибка при тестовой рассылке.")

async def force_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без изменений)
    chat = update.effective_chat
    if not chat or not await admin_only_handler(update, context): return
    if not context.args: await chat.send_message("Пожалуйста, укажите время для рассылки, например: /force_notify 09:00"); return
    time_str = context.args[0]
    try: hour, minute = map(int, time_str.split(':')); target_time = time(hour=hour, minute=minute)
    except ValueError: await chat.send_message("Неверный формат времени. Используйте ЧЧ:ММ, например: /force_notify 09:00"); return
    await chat.send_message(f"🚀 Принудительно запускаю рассылку для {time_str}...")
    service = NotificationService(context.bot)
    try:
        await service.send_scheduled_notifications(target_time)
        await chat.send_message(f"✅ Рассылка для {time_str} завершена. Проверяйте результат.")
        logger.info(f"[force_notify] Админ принудительно запустил и завершил рассылку для {time_str}")
    except Exception as e:
        logger.error(f"[force_notify] Ошибка при принудительной рассылке: {e}", exc_info=True)
        await chat.send_message(f"❌ Во время принудительной рассылки произошла ошибка. См. логи.")