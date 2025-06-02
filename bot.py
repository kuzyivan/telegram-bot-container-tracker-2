import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from telegram import BotCommand

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from db import SessionLocal
from handlers.tracking_handlers import tracking_conversation_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)")
    ])

def main():
    keep_alive()  # Автопинг для Render (если используешь)
    application = Application.builder().token(TOKEN).build()

    # ВНИМАНИЕ: Планировщик только здесь — не раньше!
    async def post_init(application):
        start_scheduler(application.bot)
        await set_bot_commands(application)
    application.post_init = post_init

    # ConversationHandler — ПЕРВЫМ!
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
    # Остальные обработчики
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    # Универсальный текст — ТОЛЬКО В КОНЦЕ!
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Бот запущен!")
    logger.info("🕓 Планировщик: задачи запущены (через post_init).")
    logger.info("🌐 Вебхук настроен на URL: %s", f"https://{RENDER_HOSTNAME}/{TOKEN}")
    logger.info("🚀 Бот готов к работе на порту %d", PORT)
    logger.info("🔗 Бот запущен на хосте: %s", RENDER_HOSTNAME)
    logger.info("🔗 Бот запущен на порту: %d", PORT)

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
