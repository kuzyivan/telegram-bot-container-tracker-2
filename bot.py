import os
import sqlite3
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from mail_reader import start_mail_checking, ensure_database_exists
from collections import defaultdict
import re

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAEK2YZlTL1N5CyHFB52RxFsjKTKIm1aJgAC2gADVp29CjMJWJBFq4ykNAQ"  # пример ID стикера
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    container_numbers = re.split(r'[\s,\n.]+' , user_input.strip())
    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()

    found = defaultdict(list)
    not_found = []

    for number in container_numbers:
        container = number.strip().upper()
        if not container:
            continue
        cursor.execute("""
            SELECT container_number, from_station, to_station, current_station,
                   operation, operation_date, waybill, km_left, forecast_days,
                   wagon_number, operation_road
            FROM tracking WHERE container_number = ?
        """, (container,))
        row = cursor.fetchone()
        if row:
            key = (row[3], row[5])  # current_station и operation_date
            found[key].append(row)
        else:
            not_found.append(container)

    conn.close()

    reply_lines = []
    for (station, date), rows in found.items():
        header = f"📍Дислокация: {station}"
        if rows[0][10]:  # operation_road
            header += f" {rows[0][10]}"
        header += f"\n🏗Операция: {rows[0][4]}\n📅 {rows[0][5]}"

        for row in rows:
            wagon_type = "полувагон" if row[9].startswith("6") else "платформа"
            text = (
                f"🚛 Контейнер: {row[0]}\n"
                f"🚇Вагон: {row[9]} {wagon_type}\n"
                f"{header}\n\n"
                f"Откуда: {row[1]}\n"
                f"Куда: {row[2]}\n\n"
                f"Накладная: {row[6]}\n"
                f"Осталось км: {row[7]}\n"
                f"📅 Прогноз прибытия: {row[8]} дн."
            )
            reply_lines.append(text)

    if not_found:
        reply_lines.append("❌ Не найдены: " + ", ".join(not_found))

    if reply_lines:
        await update.message.reply_text("\n\n".join(reply_lines[:30]))
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")

def main():
    ensure_database_exists()
    start_mail_checking()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✨ Бот запущен!")
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
