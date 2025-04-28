import os
import logging
import asyncio
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking, init_db

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы окружения
TOKEN = os.getenv('TOKEN')
DB_FILE = 'tracking.db'

if not TOKEN:
    raise ValueError("❌ Переменная окружения TOKEN не задана!")

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83d\ude80 Отправьте номер контейнера для отслеживания.")

async def track_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    container_number = update.message.text.strip().upper()
    if not container_number:
        await update.message.reply_text("\u2753 Введите корректный номер контейнера.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT departure_station, arrival_station, operation_station, operation_type, operation_datetime, waybill_number, distance_left
        FROM tracking
        WHERE container_number = ?
        ORDER BY operation_datetime DESC
        LIMIT 1
    """, (container_number,))
    result = cursor.fetchone()
    conn.close()

    if result:
        departure, arrival, op_station, op_type, op_datetime, waybill, distance = result
        message = (
            f"\ud83d\udce6 Контейнер: <b>{container_number}</b>\n"
            f"\ud83d\udecd\ufe0f Отправление: {departure}\n"
            f"\ud83d\udecd\ufe0f Назначение: {arrival}\n"
            f"\ud83d\udecb\ufe0f Станция операции: {op_station}\n"
            f"\u2705 Операция: {op_type}\n"
            f"\ud83d\udd52 Время операции: {op_datetime}\n"
            f"\ud83d\udce6 Накладная: {waybill}\n"
            f"\ud83d\udd0d Осталось км: {distance}"
        )
        await update.message.reply_html(message)
    else:
        await update.message.reply_text("\u274c Контейнер не найден в базе данных.")

# Основная функция запуска бота
async def main():
    logger.info("\u2705 Инициализация базы данных...")
    init_db()
    start_mail_checking()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_container))

    logger.info("\ud83d\ude80 Бот запущен!")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
