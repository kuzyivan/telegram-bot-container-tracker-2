from logger import get_logger
logger = get_logger(__name__)

from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from telegram import BotCommand

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from db import SessionLocal
from handlers.tracking_handlers import (
    tracking_conversation_handler,
    cancel_tracking,
    cancel_tracking_confirm
)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)"),
        BotCommand("canceltracking", "Отменить все слежения")
    ])
    logger.info("Команды бота успешно установлены.")

def main():
    logger.info("🚦 Старт бота!")
    try:
        keep_alive()
        if TOKEN is None:
            logger.critical("TOKEN must not be None. Проверь config.py")
            raise ValueError("TOKEN must not be None. Please set the TOKEN in your config.")

        application = Application.builder().token(TOKEN).build()

        async def post_init(application):
            logger.info("Инициализация: запуск проверки почты и планировщика...")
            await start_mail_checking()
            start_scheduler(application.bot)
            await set_bot_commands(application)
            logger.info("Инициализация завершена.")

        application.post_init = post_init

        # ConversationHandler — ПЕРВЫМ
        application.add_handler(tracking_conversation_handler())
        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))
        application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern="^cancel_tracking_"))
        application.add_handler(CommandHandler("canceltracking", cancel_tracking))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Все хендлеры зарегистрированы, бот готов к работе!")

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
        )

        logger.info("Работа бота завершена корректно.")

    except Exception as e:
        logger.critical("🔥 Критическая ошибка при запуске бота: %s", e, exc_info=True)

if __name__ == "__main__":
    main()