import os
import sqlite3
import logging
from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from mail_reader import start_mail_checking, ensure_database_exists
from collections import defaultdict
import re

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

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

            # Логирование запроса в stats
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    container_number TEXT,
                    user_id INTEGER,
                    username TEXT,
                    timestamp TEXT
                )
            """)
            cursor.execute("""
                INSERT INTO stats (container_number, user_id, username, timestamp)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
            """, (container, update.message.from_user.id, update.message.from_user.username))
            conn.commit()
        else:
            not_found.append(container)

    conn.close()

    reply_lines = []
    for (station, date), rows in found.items():
        header = f"📍Дислокация: {station}"
        if rows[0][10]:
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
        separator = "\n" + "═" * 30 + "\n"
        await update.message.reply_text(separator.join(reply_lines[:30]))
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM stats")
    total_requests, unique_users = cursor.fetchone()
    conn.close()

    await update.message.reply_text(
        f"📊 Всего запросов: {total_requests}\n👤 Уникальных пользователей: {unique_users}"
    )

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)")
    ])

def main():
    ensure_database_exists()
    start_mail_checking()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.post_init = set_bot_commands
    logger.info("✨ Бот запущен!")
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
