import os
import re
import sqlite3
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

# Путь к базе данных
DB_FILE = 'tracking.db'
PORT = int(os.getenv('PORT', 10000))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправьте номер контейнера или несколько через пробел 🚛")

# Обработка поиска контейнера/контейнеров
async def find_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queries = update.message.text.strip().upper().split()

    if len(queries) > 10:
        await update.message.reply_text("❗ Можно отправить не более 10 контейнеров за один раз.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    messages = []

    for query in queries:
        if not re.match(r'^[A-Z]{4}\d{7}$', query):
            messages.append(f"❌ Неверный формат номера контейнера: {query}")
            continue

        cursor.execute("SELECT * FROM tracking WHERE container_number = ?", (query,))
        rows = cursor.fetchall()

        if not rows:
            messages.append(f"❌ Контейнер {query} не найден в базе данных.")
        else:
            for row in rows:
                message = (f"🚚 Контейнер: {row[1]}\n"
                           f"Откуда: {row[2]}\n"
                           f"Куда: {row[3]}\n"
                           f"Станция операции: {row[4]}\n"
                           f"Операция: {row[5]}\n"
                           f"Дата/время: {row[6]}\n"
                           f"Накладная: {row[7]}\n"
                           f"Осталось км: {row[8]}\n"
                           f"📅 Прогноз прибытия: {row[9]} дней")
                messages.append(message)

    conn.close()

    await update.message.reply_text('\n\n'.join(messages))

# Проверка базы данных на старте
def check_database():
    if not os.path.exists(DB_FILE):
        logger.warning("⚠️ Файл базы данных tracking.db не найден. Будет создан новый файл.")

# Основной запуск
if __name__ == '__main__':
    check_database()

    start_mail_checking()
    start_backup_scheduler()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, find_container))

    if WEBHOOK_URL:
        logger.info(f"✨ Бот запущен!\n🌐 Используется вебхук: {WEBHOOK_URL}")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=f"{WEBHOOK_URL}/")
    else:
        logger.info("✨ Бот запущен!")
        app.run_polling()
