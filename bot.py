import os
import re
import sqlite3
import logging
import pandas as pd
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from mail_reader import start_mail_checking, ensure_database_exists as ensure_db_mail_reader

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def ensure_database():
    """
    Создаёт две таблицы:
    - tracking (из mail_reader.ensure_database_exists)
    - stats   (для логирования запросов пользователей)
    """
    # создаём таблицу tracking через mail_reader
    ensure_db_mail_reader()
    # дополняем stats
    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_number TEXT,
            user_id INTEGER,
            username TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = (
        "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    )
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь номер контейнера для отслеживания.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    container_numbers = [
        c.strip().upper()
        for c in re.split(r'[\s,\n.]+', text)
        if c.strip()
    ]

    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()

    found = []
    not_found = []
    for cn in container_numbers:
        cursor.execute("""
            SELECT container_number, from_station, to_station, current_station,
                   operation, operation_date, waybill, km_left, forecast_days,
                   wagon_number, operation_road
            FROM tracking WHERE container_number = ?
        """, (cn,))
        row = cursor.fetchone()
        if row:
            found.append(row)
            cursor.execute("""
                INSERT INTO stats (container_number, user_id, username, timestamp)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
            """, (
                cn,
                update.effective_user.id,
                update.effective_user.username or "—"
            ))
            conn.commit()
        else:
            not_found.append(cn)
    conn.close()

    if not found:
        return await update.message.reply_text("Ничего не найдено.")

    # если больше одного — Excel
    if len(found) > 1:
        df = pd.DataFrame(found, columns=[
            'Номер контейнера','Станция отправления','Станция назначения',
            'Станция операции','Операция','Дата и время операции',
            'Номер накладной','Осталось км','Прогноз (дн.)',
            'Номер вагона','Дорога операции'
        ])
        fname = f"/tmp/containers_{datetime.now():%H%M}.xlsx"
        df.to_excel(fname, index=False)
        await update.message.reply_document(
            document=open(fname, "rb"),
            filename=os.path.basename(fname)
        )
        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # один контейнер — текст
    row = found[0]
    wagon_type = "полувагон" if row[9].startswith("6") else "платформа"
    reply = (
        f"🚛 Контейнер: {row[0]}\n"
        f"🚇 Вагон: {row[9]} ({wagon_type})\n"
        f"📍 Дислокация: {row[3]} {row[10]}\n"
        f"🏗 Операция: {row[4]} — {row[5]}\n\n"
        f"Откуда: {row[1]}\n"
        f"Куда: {row[2]}\n\n"
        f"Накладная: {row[6]}\n"
        f"🛣 Осталось км: {row[7]}\n"
        f"⏳ Прогноз: {row[8]} дн."
    )
    await update.message.reply_text(reply)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COALESCE(username,'—'), COUNT(*), GROUP_CONCAT(DISTINCT container_number)
          FROM stats
      GROUP BY user_id
      ORDER BY COUNT(*) DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return await update.message.reply_text("Нет статистики.")
    lines = ["📊 Статистика:"]
    for uid, uname, cnt, cnts in rows:
        lines.append(f"👤 {uname} (ID:{uid}) — {cnt} запросов, контейнеров: {cnts}")
    await update.message.reply_text("\n".join(lines))


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = sqlite3.connect("tracking.db")
    df = pd.read_sql_query("SELECT * FROM stats", conn)
    conn.close()
    if df.empty:
        return await update.message.reply_text("Нет данных.")
    path = f"/tmp/stats_{datetime.now():%H%M}.xlsx"
    df.to_excel(path, index=False)
    await update.message.reply_document(document=open(path, "rb"), filename=os.path.basename(path))


async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать"),
        BotCommand("stats", "Просмотр статистики (админ)"),
        BotCommand("exportstats", "Экспорт статистики (админ)"),
    ])


# ————— фоновые задачи —————
async def auto_ping(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.get_me()
        logger.info("📡 Auto-ping OK")
    except Exception as e:
        logger.warning("⚠ Auto-ping failed: %s", e)


async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🟢 Heartbeat")


def main():
    ensure_database()
    start_mail_checking()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("exportstats", exportstats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.post_init = set_commands

    # запуск фоновых задач через JobQueue
    jq = app.job_queue
    jq.run_repeating(auto_ping, interval=5*60, first=0)
    jq.run_repeating(keep_alive, interval=60, first=0)

    # webhook
    logger.info("✨ Бот стартует")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )


if __name__ == "__main__":
    main()
