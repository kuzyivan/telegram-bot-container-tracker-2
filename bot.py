import os
import sqlite3
import re
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mail_reader import start_mail_checking

# Настройки из переменных окружения
TOKEN = os.getenv('TOKEN')
DB_FILE = 'tracking.db'

if not TOKEN:
    raise ValueError("❌ Переменная окружения TOKEN не задана!")

# Команда start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь номер контейнера, чтобы получить информацию о нём 🚛")

# Поиск контейнера
async def find_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().upper()

    # Проверка на валидный номер контейнера (буквы + цифры, 11 символов)
    if not re.match(r'^[A-Z]{4}\d{7}$', query):
        await update.message.reply_text("❗ Пожалуйста, отправьте корректный номер контейнера (например, MSKU1234567).")
        return

    waiting_message = await update.message.reply_text("🔍 Ищу контейнер в базе данных...")
    await asyncio.sleep(1)  # имитация загрузки

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tracking WHERE container_number = ?", (query,))
    rows = cursor.fetchall()
    conn.close()

    await waiting_message.delete()

    if not rows:
        await update.message.reply_text("❌ Контейнер не найден в базе данных.")
    else:
        messages = []
        for row in rows:
            message = (f"\U0001F69A Контейнер: {row[1]}\n"
                       f"Откуда: {row[2]}\n"
                       f"Куда: {row[3]}\n"
                       f"Станция операции: {row[4]}\n"
                       f"Операция: {row[5]}\n"
                       f"Дата/время: {row[6]}\n"
                       f"Накладная: {row[7]}\n"
                       f"Осталось км: {row[8]}")
            messages.append(message)
        await update.message.reply_text('\n\n'.join(messages))

# Запуск бота
if __name__ == '__main__':
    start_mail_checking()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), find_container))

    print("✨ Бот запущен!")
    app.run_polling()
