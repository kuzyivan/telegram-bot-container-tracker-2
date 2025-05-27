from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from utils.keep_alive import keep_alive
from handlers.user_handlers import start, handle_sticker, handle_message
from handlers.admin_handlers import stats, exportstats
import logging
from db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)")
    ])

# Middleware — добавляет сессию к каждому update
async def session_middleware(update, context, next_handler):
    async with SessionLocal() as session:
        context.session = session
        return await next_handler(update, context)

def main():
    start_mail_checking()
    keep_alive()

    application = Application.builder().token(TOKEN).build()

    # Добавляем middleware в начало цепочки
    application.add_middleware(session_middleware)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.post_init = set_bot_commands

    print("✅ Webhook init checkpoint OK")

    logger.info("✨ Бот запущен!")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
