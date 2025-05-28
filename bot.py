import asyncio
import logging
from telegram.ext import Application, CommandHandler
from handlers.tracking_handlers import tracking_conversation_handler, stop_tracking, testnotify
from handlers.user_handlers import start, handle_message
from handlers.admin_handlers import exportstats
from scheduler import start_scheduler
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Основные хендлеры
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stoptracking", stop_tracking))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("testnotify", testnotify))
    application.add_handler(tracking_conversation_handler())
    application.add_handler(CommandHandler("msg", handle_message))

    # Запуск планировщика уведомлений
    start_scheduler(application.bot)

    application.run_webhook(
        listen="0.0.0.0",
        port=10000,
        webhook_url=f"https://atermtrackbot2.onrender.com/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    asyncio.run(main())

