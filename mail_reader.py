import os
import sqlite3
import re
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking, ensure_database_exists
from backup_db import start_backup_scheduler

# Настройки из переменных окружения
TOKEN = os.getenv('TELEGRAM_TOKEN')
PORT = int(os.getenv('PORT', 10000))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
DB_FILE = 'tracking.db'

if not TOKEN:
    raise ValueError("❌ Переменная окружения TELEGRAM_TOKEN не задана!")

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Проверка существования базы данных и таблицы

def check_database():
    if not os.path.exists(DB_FILE):
        logger.warning("⚠️ Файл базы данных tracking.db не найден. Будет создан новый файл.")
        return False

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracking';")
        table_exists = cursor.fetchone()
        if not table_exists:
            logger.warning("⚠️ Таблица 'tracking' отсутствует в базе данных. Будет создана новая таблица.")
            return False
    finally:
        conn.close()

    logger.info("✅ База данных и таблица 'tracking' найдены.")
    return True

# Команда start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь номер контейнера, чтобы получить информацию о нём 🚛")

# Поиск контейнера
async def find_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().upper()

    if not re.match(r'^[A-Z]{4}\d{7}$', query):
        await update.message.reply_text("❗ Пожалуйста, отправьте корректный номер контейнера (например, MSKU1234567).")
        return

    waiting_message = await update.message.reply_text("🔍 Ищу контейнер в базе данных...")
    await asyncio.sleep(1)

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracking WHERE container_number = ?", (query,))
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка при работе с базой данных: {e}")
        await update.message.reply_text("❌ Ошибка при обращении к базе данных.")
        return
    finally:
        conn.close()

    await waiting_message.delete()

    if not rows:
        logger.info(f"Контейнер {query} не найден в базе данных.")
        await update.message.reply_text("❌ Контейнер не найден в базе данных.")
    else:
        logger.info(f"Контейнер {query} найден, найдено записей: {len(rows)}.")
        messages = []
        for row in rows:
            message = (f"\U0001F69A Контейнер: {row[1]}\n"
                       f"Откуда: {row[2]}\n"
                       f"Куда: {row[3]}\n"
                       f"Станция операции: {row[4]}\n"
                       f"Операция: {row[5]}\n"
                       f"Дата/время: {row[6]}\n"
                       f"Накладная: {row[7]}\n"
                       f"Осталось км: {row[8]}")
            messages.append(message)
        await update.message.reply_text('\n\n'.join(messages))

# Запуск бота
if __name__ == '__main__':
    if not check_database():
        ensure_database_exists()

    logger.info("📩 Проверка почты...")
    start_mail_checking()
    logger.info("🔄 Планировщик бэкапа базы данных запущен.")
    start_backup_scheduler()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), find_container))

    logger.info("✨ Бот запущен!")

    if WEBHOOK_URL:
        logger.info(f"Используется вебхук: {WEBHOOK_URL}")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL)
    else:
        logger.info("Используется polling режим.")
        app.run_polling()
