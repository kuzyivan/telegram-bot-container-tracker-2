import os
import sqlite3
import logging
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, BotCommand, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from mail_reader import start_mail_checking, ensure_database_exists
from collections import defaultdict
import re
import tempfile

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
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]

    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()

    found_rows = []
    not_found = []

    for number in container_numbers:
        cursor.execute("""
            SELECT container_number, from_station, to_station, current_station,
                   operation, operation_date, waybill, km_left, forecast_days,
                   wagon_number, operation_road
            FROM tracking WHERE container_number = ?
        """, (number,))
        row = cursor.fetchone()
        if row:
            found_rows.append(row)

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
            """, (number, update.message.from_user.id, update.message.from_user.username))
            conn.commit()
        else:
            not_found.append(number)

    conn.close()

    if len(container_numbers) > 1 and found_rows:
        df = pd.DataFrame(found_rows, columns=[
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
    df.to_excel(tmp.name, index=False)
    message = f"📦 Вот твоя дислокация! В файле — {len(found_rows)} контейнер(ов)."
    if not_found:
        message += f"\n\n❌ Не найдены: {', '.join(not_found)}"
    message += "\n\n⬇️ Скачай Excel ниже:"
    await update.message.reply_text(message)
    await update.message.reply_document(document=open(tmp.name, "rb"), filename="контейнеры.xlsx")

    if found_rows:
        reply_lines = []
        for row in found_rows:
            wagon_type = "полувагон" if row[9].startswith("6") else "платформа"
            reply_lines.append(
                f"🚛 Контейнер: {row[0]}\n"
                f"🚇 Вагон: {row[9]} {wagon_type}\n"
                f"📍Дислокация: {row[3]} {row[10]}\n"
                f"🏗 Операция: {row[4]}\n📅 {row[5]}\n\n"
                f"Откуда: {row[1]}\nКуда: {row[2]}\n\n"
                f"Накладная: {row[6]}\nОсталось км: {row[7]}\n"
                f"📅 Прогноз прибытия: {row[8]} дн."
            )
        await update.message.reply_text("\n" + "═" * 30 + "\n".join(reply_lines))
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COALESCE(username, '—'), COUNT(*), GROUP_CONCAT(DISTINCT container_number)
        FROM stats
        GROUP BY user_id
        ORDER BY COUNT(*) DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Нет данных для отчета.")
        return

    report_lines = ["📊 Отчет по пользователям:"]
    for user_id, username, count, containers in rows:
        report_lines.append(
            f"\n👤 `{user_id}` ({username})\n"
            f"📦 Запросов: {count}\n"
            f"🧾 Контейнеры: {containers}"
        )

    await update.message.reply_text("\n".join(report_lines[:30]), parse_mode="Markdown")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = sqlite3.connect("tracking.db")
    df = pd.read_sql_query("SELECT * FROM stats", conn)
    conn.close()

    if df.empty:
        await update.message.reply_text("Нет данных для экспорта.")
        return

    file_path = "user_stats.xlsx"
    df.to_excel(file_path, index=False)

    await update.message.reply_document(InputFile(file_path))
    os.remove(file_path)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)")
    ])

def main():
    ensure_database_exists()
    start_mail_checking()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
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

