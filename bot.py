import os
import sqlite3
import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_FILE = "tracking.db"
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Проверка переменных окружения
if not TOKEN:
    raise ValueError("❌ Переменная окружения TELEGRAM_TOKEN не задана!")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Введите номер контейнера или несколько, чтобы получить информацию 📦")

# Поиск контейнера(ов)
async def find_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    raw_ids = re.split(r"[,\.\s\n]+", text)
    container_ids = [c.strip().upper() for c in raw_ids if c.strip()]
    if not container_ids:
        await update.message.reply_text("❗ Не распознаны номера контейнеров.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    found = []
    not_found = []

    for cid in container_ids:
        cursor.execute("SELECT * FROM tracking WHERE container_number = ?", (cid,))
        rows = cursor.fetchall()
        if rows:
            found.extend(rows)
        else:
            not_found.append(cid)
    conn.close()

    if not found:
        await update.message.reply_text("❌ Контейнеры не найдены в базе данных.")
        return

    # Группировка по станции и дате
    grouped = {}
    for row in found:
        key = (row[4], row[6])  # current_station, operation_date
        grouped.setdefault(key, []).append(row)

    reply_lines = []
    for (station, date), group in grouped.items():
        header = f"🏗️ {station}\n📅 {date}"
        containers = []
        for row in group:
            forecast = f"{round(row[8] / 600, 1)} дн." if row[8] else "-"
            containers.append(
                f"🚛 Контейнер: {row[1]}\n"
                f"Откуда: {row[2]}\n"
                f"Куда: {row[3]}\n"
                f"Операция: {row[5]}\n"
                f"Накладная: {row[7]}\n"
                f"Осталось км: {row[8]}\n"
                f"📅 Прогноз прибытия: {forecast}"
            )
        reply_lines.append(f"{header}\n\n" + "\n\n".join(containers))

    if not_found:
        reply_lines.append(
            "⚠️ Не найдены в базе:\n" + ", ".join(not_found)
        )

    await update.message.reply_text("\n\n".join(reply_lines[:30]))  # ограничение на длину сообщения

# Инициализация бота
if __name__ == "__main__":
    start_mail_checking()
    start_backup_scheduler()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, find_container))
    logger.info("✨ Бот запущен!")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/"
    )
