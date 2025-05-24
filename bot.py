import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime
from telegram import Update, BotCommand, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from mail_reader import start_mail_checking, ensure_database_exists

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    container_numbers = [
        c.strip().upper()
        for c in re.split(r'[\s,\n.]+', user_input.strip())
        if c
    ]

    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()

    found = []
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
            found.append(row)
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
            """, (number, update.effective_user.id, update.effective_user.username))
            conn.commit()
        else:
            not_found.append(number)

    conn.close()

    if not found:
        return await update.message.reply_text("Ничего не найдено по введённым номерам.")

    # Если несколько контейнеров — отправляем Excel
    if len(found) > 1:
        df = pd.DataFrame(found, columns=[
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Осталось км', 'Прогноз (дн.)',
            'Номер вагона', 'Дорога операции'
        ])
        tmp_name = f"/tmp/containers_{datetime.now():%H%M}.xlsx"
        df.to_excel(tmp_name, index=False)

        await update.message.reply_document(
            document=open(tmp_name, "rb"),
            filename=os.path.basename(tmp_name)
        )
        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # Один контейнер — текстовый ответ
    row = found[0]
    wagon_type = "полувагон" if row[9].startswith("6") else "платформа"
    text = (
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
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = sqlite3.connect("tracking.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COALESCE(username, '—'), COUNT(*), 
               GROUP_CONCAT(DISTINCT container_number)
          FROM stats
      GROUP BY user_id
      ORDER BY COUNT(*) DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return await update.message.reply_text("Нет статистики.")
    reply = ["📊 Статистика использования:"]
    for uid, uname, cnt, cnts in rows:
        reply.append(
            f"👤 {uname} (ID {uid}):\n"
            f"  Запросов: {cnt}\n"
            f"  Контейнеров: {cnts}"
        )
    await update.message.reply_text("\n\n".join(reply))


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = sqlite3.connect("tracking.db")
    df = pd.read_sql_query("SELECT * FROM stats", conn)
    conn.close()
    if df.empty:
        return await update.message.reply_text("Нет данных для экспорта.")
    path = f"/tmp/stats_{datetime.now():%H%M}.xlsx"
    df.to_excel(path, index=False)
    await update.message.reply_document(document=open(path, "rb"), filename=os.path.basename(path))


async def set_bot_commands(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу"),
        BotCommand("stats", "Показать статистику (админ)"),
        BotCommand("exportstats", "Выгрузить статистику в Excel (админ)"),
    ])


# ————— фоновые задачи —————

async def auto_ping(context: ContextTypes.DEFAULT_TYPE):
    """Пинг Telegram API, чтобы Render видел трафик."""
    try:
        await context.bot.get_me()
        logger.info("📡 Auto-ping успешен.")
    except Exception as e:
        logger.warning(f"⚠ Auto-ping ошибка: {e}")


async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    """Просто лог, чтобы Render считал приложение активным."""
    logger.info("🟢 Keep-alive heartbeat.")


def main():
    # Инициализация БД и первичная проверка почты
    ensure_database_exists()
    start_mail_checking()

    # Сборка приложения
    application = Application.builder().token(TOKEN).build()

    # Регистрация хэндлеров
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.post_init = set_bot_commands

    # Расписание фоновых задач
    jq = application.job_queue
    # каждые 5 минут – авто-пинг
    jq.run_repeating(auto_ping, interval=5 * 60, first=0)
    # каждую минуту – heartbeat-лог
    jq.run_repeating(keep_alive, interval=60, first=0)

    # Запуск webhook
    logger.info("✨ Бот запущен!")
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )


if __name__ == "__main__":
    main()
