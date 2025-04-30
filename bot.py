import os
import sqlite3
import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

# Настройки
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))
DB_FILE = "tracking.db"

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Введи один или несколько номеров контейнеров через пробел, запятую, точку или с новой строки.")

# Обработка контейнеров
async def handle_container_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    raw_containers = re.split(r"[\s,\.\n]+", text)
    containers = [c.strip().upper() for c in raw_containers if c.strip()]

    if not containers:
        await update.message.reply_text("⚠️ Не распознаны номера контейнеров. Попробуйте снова.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    found_messages = []
    not_found = []

    for number in containers:
        cursor.execute("SELECT * FROM tracking WHERE container_number = ?", (number,))
        rows = cursor.fetchall()
        if not rows:
            not_found.append(number)
            continue

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
            found_messages.append(message)

    conn.close()

    reply_parts = found_messages
    if not_found:
        reply_parts.append("\n❌ Не найдены в базе:\n" + "\n".join(f"- {c}" for c in not_found))

    await update.message.reply_text("\n\n".join(reply_parts))

# Запуск
if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("❌ Переменная окружения TOKEN не задана!")

    start_mail_checking()
    start_backup_scheduler()

    app = ApplicationBuilder().token(TOKEN).webhook_url(WEBHOOK_URL).port(PORT).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_container_query))

    logger.info("✨ Бот запущен!")
    logger.info(f"🌐 Используется вебхук: {WEBHOOK_URL}")

    app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL)
