import asyncio
import logging
from telegram.ext import ApplicationBuilder
from user_handlers import main_conversation_handler, stop_tracking
from tracking_handlers import tracking_conversation_handler
from admin_handlers import admin_handler, stats_handler, exportstats_handler
from scheduler import start_scheduler
from config import BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Основные команды
    application.add_handler(main_conversation_handler())
    application.add_handler(tracking_conversation_handler())
    application.add_handler(admin_handler)
    application.add_handler(stats_handler)
    application.add_handler(exportstats_handler)
    application.add_handler(stop_tracking)

    # Планировщик — запускаем после старта loop
    start_scheduler(application.bot)

    # Запуск бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
