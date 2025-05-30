import logging
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import BotCommand

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import start, handle_sticker, handle_message, show_menu
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from db import SessionLocal
from handlers.tracking_handlers import tracking_conversation_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    print("[DEBUG] set_bot_commands called")
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)"),
        BotCommand("testnotify", "Тестовая отправка дислокации (админ)")
    ])

def main():
    start_mail_checking()
    keep_alive()

    application = Application.builder().token(TOKEN).build()

    async def post_init(application):
        print("[DEBUG] post_init called")
        start_scheduler(application.bot)
        await set_bot_commands(application)
    application.post_init = post_init

    application.add_handler(tracking_conversation_handler())
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))

    print("✅ Webhook init checkpoint OK")
    print("DEBUG: got containers for tracking")
    logger.info("✨ Бот запущен!")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()