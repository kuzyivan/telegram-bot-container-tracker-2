import asyncio
import logging
from telegram.ext import Application, CommandHandler
from handlers.tracking_handlers import tracking_conversation_handler, stop_tracking, testnotify
from handlers.user_handlers import start, handle_message
from handlers.admin_handlers import exportstats
from scheduler import start_scheduler
from config import TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    application = Application.builder().token(TOKEN).build()

    # Основные хендлеры
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stoptracking", stop_tracking))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("testnotify", testnotify))
    application.add_handler(tracking_conversation_handler())
    application.add_handler(CommandHandler("msg", handle_message))

    # Старт планировщика уведомлений — строго после запуска loop
    async def on_startup(app):
        start_scheduler(app.bot)
        logger.info("✅ Планировщик уведомлений запущен")

    application.post_init = on_startup

    await application.run_webhook(
        listen="0.0.0.0",
        port=10000,
        webhook_url=f"https://atermtrackbot2.onrender.com/{TOKEN}"
    )

if __name__ == "__main__":
    asyncio.run(main())
