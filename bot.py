import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import sqlite3
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DB_FILE = 'tracking.db'
PORT = int(os.environ.get('PORT', 10000))

# Поиск информации по номеру контейнера
async def track_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    container_number = update.message.text.strip().upper()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT departure_station, arrival_station, operation_station, operation_type, operation_datetime, waybill_number, distance_left
        FROM tracking
        WHERE container_number = ?
        ORDER BY operation_datetime DESC
        LIMIT 1
    ''', (container_number,))
    row = cursor.fetchone()
    conn.close()

    if row:
        departure, arrival, op_station, op_type, op_datetime, waybill, distance = row
        reply = (
            f"📦 Контейнер: {container_number}\n"
            f"🚉 Отправление: {departure}\n"
            f"🚊 Назначение: {arrival}\n"
            f"🚄 Станция операции: {op_station}\n"
            f"✅ Операция: {op_type}\n"
            f"🕒 Время операции: {op_datetime}\n"
            f"💳 Накладная: {waybill}\n"
            f"🌍 Остаток км: {distance}"
        )
    else:
        reply = "❌ Контейнер не найден в базе данных."

    await update.message.reply_text(reply)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Отправьте номер контейнера для отслеживания.")

if __name__ == '__main__':
    start_mail_checking()
    start_backup_scheduler()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_container))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TELEGRAM_TOKEN}"
    )
