import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    BaseMiddleware,
)
from telegram import BotCommand
from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import start, handle_sticker, handle_message, show_menu
from handlers.admin_handlers import stats, exportstats, tracking
from handlers.tracking_handlers import tracking_conversation_handler
from db import SessionLocal  # Должен быть async_sessionmaker!

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Middleware для SQLAlchemy session (async)
class SQLAlchemySessionMiddleware(BaseMiddleware):
    async def __call__(self, update, context, next_handler):
        async with SessionLocal() as session:
            context.session = session
            return await next_handler(update, context)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("stats", "Статистика запросов (для администратора)"),
        BotCommand("exportstats", "Выгрузка всех запросов в Excel (админ)"),
        BotCommand("menu", "Главное меню"),
        BotCommand("tracking", "Отследить контейнер/вагон")
    ])

async def error_handler(update, context):
    logger.error(f"Exception: {context.error}", exc_info=context.error)

async def post_init(application):
    await set_bot_commands(application)
    start_scheduler(application)

def main():
    # Фоновые задачи
    start_mail_checking()
    keep_alive()

    # Создаём Application (PTB v22+)
    application = ApplicationBuilder().token(TOKEN).build()

    # Middleware для передачи session во все context
    application.add_middleware(SQLAlchemySessionMiddleware())

    # Обработчики команд
    application.add_handler(tracking_conversation_handler())
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Если есть CallbackQueryHandler для inline-кнопок, добавь сюда
    # application.add_handler(CallbackQueryHandler(...))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # post_init: запуск команд и scheduler после старта
    application.post_init = post_init

    logger.info("✨ Бот запущен!")

    # Для webhooks (PTB[webhooks] должен быть установлен!)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
