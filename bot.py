import asyncio
from dotenv import load_dotenv
load_dotenv()

from logger import get_logger
logger = get_logger(__name__)

from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat

from config import TOKEN, ADMIN_CHAT_ID
from mail_reader import start_mail_checking
from scheduler import start_scheduler

from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler,
    set_email_command, process_email, cancel_email
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from handlers.tracking_handlers import (
    tracking_conversation_handler, cancel, cancel_tracking_confirm
)
from handlers.broadcast import broadcast_conversation_handler


# === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ===
async def error_handler(update, context):
    logger.error("❗️Произошла необработанная ошибка: %s", context.error, exc_info=True)


# === КОМАНДЫ ===
async def set_bot_commands(application):
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("canceltracking", "Отменить все слежения"),
        BotCommand("set_email", "Указать e-mail для отчётов"),
        BotCommand("email_off", "Отключить рассылку на e-mail"),
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Команды для пользователей установлены.")

    admin_commands = user_commands + [
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)"),
        BotCommand("tracking", "Выгрузка подписок (админ)"),
        BotCommand("broadcast", "Рассылка (админ)"),
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Админ-команды установлены (ID: {ADMIN_CHAT_ID})")


# === ТОЧКА ЗАПУСКА ===
async def main():
    logger.info("🚦 Старт бота!")

    application = Application.builder().token(TOKEN).build()

    # === Хендлер set_email ===
    SET_EMAIL = range(1)
    set_email_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("set_email", set_email_command)],
        states={SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]},
        fallbacks=[CommandHandler("cancel", cancel_email)],
    )
    application.add_handler(set_email_conv_handler)

    # === POST INIT ===
    async def post_init(app):
        logger.info("⚙️ Запуск фоновых задач...")
        await start_mail_checking()
        start_scheduler(app.bot)
        await set_bot_commands(app)
        logger.info("✅ post_init завершён.")

    application.post_init = post_init

    # === Остальные хендлеры ===
    application.add_handler(broadcast_conversation_handler)
    application.add_handler(tracking_conversation_handler())
    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
    application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
    application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern="^cancel_tracking_"))

    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("canceltracking", cancel))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))

    application.add_handler(MessageHandler(
        filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
        reply_keyboard_handler
    ))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_error_handler(error_handler)

    logger.info("🤖 Бот готов к запуску. Запускаем polling...")
    await application.run_polling()


# === ЗАПУСК ===
if __name__ == "__main__":
    asyncio.run(main())