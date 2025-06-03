import logging
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
from handlers.tracking_handlers import tracking_conversation_handler, cancel_tracking

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)"),
        BotCommand("canceltracking", "Отменить все слежения")  # новая команда
    ])

def main():
    keep_alive()
    application = Application.builder().token(TOKEN).build()

    async def post_init(application):
        await start_mail_checking()                # ВАЖНО: теперь await!
        start_scheduler(application.bot)
        await set_bot_commands(application)
    application.post_init = post_init

    # Важно! ConversationHandler — ПЕРВЫМ
    application.add_handler(tracking_conversation_handler())
    # Inline-меню
    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
    application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
    # Команды
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("start", start))
    # ReplyKeyboard обработчик
    application.add_handler(MessageHandler(
        filters.Regex("^(📦 Дислокация|🔔 Задать слежение)$"),
        reply_keyboard_handler
    ))
    application.add_handler(CommandHandler("canceltracking", cancel_tracking))
    # Остальные обработчики
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    # Универсальный текст — ТОЛЬКО В КОНЦЕ!
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Бот запущен!")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
