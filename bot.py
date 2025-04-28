import os
import logging
import sqlite3
import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

# Путь к базе данных, созданной mail_reader.py
DB_FILE = 'tracking.db'
PORT = int(os.getenv('PORT', 10000))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Telegram-приложения
app = ApplicationBuilder().token(BOT_TOKEN).build()

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я AtermTrackBot. Напиши номер контейнера, и я покажу его последний статус."  
    )

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Просто отправь номер контейнера или несколько номеров через пробел/запятую, и я отвечу последними данными."
    )

# Обработчик текстовых сообщений с номерами контейнеров
async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    containers = [c for c in re.split(r'[\s,;:\n\r\.]+', text) if c]
    if not containers:
        await update.message.reply_text("⚠️ Не найдено ни одного контейнера в сообщении.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in containers)
        query = f"""
            SELECT container_number, departure_station, arrival_station,
                   operation_station, operation_type, operation_datetime,
                   waybill_number, distance_left
            FROM tracking
            WHERE container_number IN ({placeholders})
            ORDER BY operation_datetime DESC
        """
        rows = cursor.execute(query, containers).fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("⚠️ Контейнеры не найдены в базе.")
            return

        latest = {}
        for row in rows:
            cn = row[0]
            if cn not in latest:
                latest[cn] = row

        routes = {}
        for row in latest.values():
            cn, dep, arr, op_station, op_type, op_dt, waybill, dist = row
            route_key = (dep, arr)
            routes.setdefault(route_key, []).append((cn, op_station, op_type, op_dt, waybill, dist))

        reply = "📦 Отчёт по контейнерам:\n"
        for (dep, arr), ops in routes.items():
            reply += f"\n🚆 Маршрут: {dep} → {arr}\n"
            for cn, op_station, op_type, op_dt, waybill, dist in ops:
                station = (op_station or 'Неизвестно').split('(')[0].strip().upper()
                dt_str = op_dt if isinstance(op_dt, str) else str(op_dt)
                reply += (
                    f"📦 {cn}\n"
                    f"📍 Станция: {station}\n"
                    f"⚙️ Операция: {op_type}\n"
                    f"🕓 Время: {dt_str}\n"
                    f"📦 Накладная: {waybill}\n"
                    f"📅 Осталось км: {dist}\n"
                )
        await update.message.reply_text(reply)

    except Exception as e:
        logger.exception("Ошибка при запросе контейнеров")
        await update.message.reply_text("⚠️ Произошла ошибка при обработке. Попробуйте позже.")

# Регистрация хендлеров
app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('help', help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track))

if __name__ == '__main__':
    # Запуск фоновых задач
    start_mail_checking()
    start_backup_scheduler()

    # Запуск бота через webhook
    app.run_webhook(
        listen='0.0.0.0',
        port=PORT,
        url_path='webhook',
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )
