from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import TOKEN, PORT, RENDER_HOSTNAME
from db import get_pg_connection
from mail_reader import start_mail_checking
from utils.keep_alive import keep_alive
from handlers.user_handlers import start, handle_sticker, handle_message
from handlers.admin_handlers import stats, exportstats
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ensure_database_exists():
    conn = get_pg_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracking (
            container_number TEXT,
            from_station TEXT,
            to_station TEXT,
            current_station TEXT,
            operation TEXT,
            operation_date TEXT,
            waybill TEXT,
            km_left TEXT,
            forecast_days TEXT,
            wagon_number TEXT,
            operation_road TEXT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id SERIAL PRIMARY KEY,
            container_number TEXT,
            user_id BIGINT,
            username TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()

async def set_bot_commands(application):
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)")
    ])

def main():
    ensure_database_exists()
    start_mail_checking()
    keep_alive()

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
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
