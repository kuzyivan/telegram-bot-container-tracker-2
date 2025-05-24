import os
import sqlite3
import logging
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, BotCommand, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from mail_reader import check_mail_and_update_database
from collections import defaultdict
import re
import tempfile
from datetime import datetime, timedelta
import psycopg2
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # ← добавь эту строку

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT", 5432),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

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

    conn = get_pg_connection()
    cursor = conn.cursor()

    found_rows = []
    not_found = []

    for number in container_numbers:
        cursor.execute("""
            SELECT container_number, from_station, to_station, current_station,
                   operation, operation_date, waybill, km_left, forecast_days,
                   wagon_number, operation_road
            FROM tracking WHERE container_number = %s
        """, (number,))
        row = cursor.fetchone()
        if row:
            found_rows.append(row)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    id SERIAL PRIMARY KEY,
                    container_number TEXT,
                    user_id BIGINT,
                    username TEXT,
                    timestamp TIMESTAMP DEFAULT NOW()
                )
            """)
            cursor.execute("""
                INSERT INTO stats (container_number, user_id, username)
                VALUES (%s, %s, %s)
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
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Дислокация')
                workbook = writer.book
                worksheet = writer.sheets['Дислокация']
            
                # Заливка для шапки
                from openpyxl.styles import PatternFill
                fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for cell in worksheet[1]:
                    cell.fill = fill
            
                # Автоширина столбцов
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
                    adjusted_width = max_length + 2
                    worksheet.column_dimensions[col[0].column_letter].width = adjusted_width

            from datetime import datetime, timedelta

            vladivostok_time = datetime.utcnow() + timedelta(hours=10)
            filename = f"Дислокация {vladivostok_time.strftime('%H-%M')}.xlsx"
            await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

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

    conn = get_pg_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
               STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
        FROM stats
        GROUP BY user_id, username
        ORDER BY запросов DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Нет статистики.")
        return

    text = "📊 Статистика использования:\n\n"
    for row in rows:
        text += f"👤 {row[1]} (ID: {row[0]})\n" \
                f"Запросов: {row[2]}\n" \
                f"Контейнеры: {row[3]}\n\n"

    await update.message.reply_text(text)

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = get_pg_connection()
    df = pd.read_sql_query("SELECT * FROM stats", conn)
    conn.close()

    if df.empty:
        await update.message.reply_text("Нет данных для экспорта.")
        return

    from openpyxl.styles import PatternFill
    from datetime import datetime, timedelta
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Статистика')
            workbook = writer.book
            worksheet = writer.sheets['Статистика']

            # Заливка шапки таблицы
            header_fill = PatternFill(start_color='FFD673', end_color='FFD673', fill_type='solid')
            for cell in worksheet[1]:
                cell.fill = header_fill

            # Автоширина столбцов
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

        # Имя файла с учетом Владивостокского времени
        vladivostok_time = datetime.utcnow() + timedelta(hours=10)
        filename = f"Статистика {vladivostok_time.strftime('%H-%M')}.xlsx"
        await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)
async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)")
    ])

async def autoping(bot):
    while True:
        try:
            await bot.get_me()  # Пингует Telegram API
            logger.info("📡 Автопинг выполнен успешно.")
        except Exception as e:
            logger.warning(f"⚠ Ошибка автопинга: {e}")
        await asyncio.sleep(60 * 5)  # каждые 5 минут

async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    application = Application.builder().token(TOKEN).build()

    # Команды бота
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Планировщик задач
    scheduler = AsyncIOScheduler(timezone="Asia/Vladivostok")
    scheduler.add_job(check_mail_and_update_database, 'interval', minutes=15)
    scheduler.start()

    # 🟢 Запуск автопинга
    asyncio.create_task(autoping(application.bot))

    # Запуск бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
    
