from logger import get_logger
logger = get_logger(__name__)

from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler,
    set_email_command, process_email, cancel_email
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from db import SessionLocal
from handlers.tracking_handlers import (
    tracking_conversation_handler,
    cancel,
    cancel_tracking_confirm
)
from handlers.broadcast import broadcast_conversation_handler

# === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ===
async def error_handler(update, context):
    logger.error("❗️Произошла необработанная ошибка: %s", context.error, exc_info=True)
    # Если хочешь, можешь уведомить админа вот так:
    # try:
    #     await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❗️Ошибка: {context.error}")
    # except Exception as send_err:
    #     logger.error("Ошибка отправки уведомления админу: %s", send_err, exc_info=True)

async def set_bot_commands(application):
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("canceltracking", "Отменить все слежения"),
    ]
    await application.bot.set_my_commands(
        commands=user_commands,
        scope=BotCommandScopeDefault()
    )
    logger.info("Установлены команды для обычных пользователей.")

    admin_commands = user_commands + [
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)"),
        BotCommand("tracking", "Выгрузка подписок (админ)"),
        BotCommand("broadcast", "Рассылка (админ)"),
    ]
    await application.bot.set_my_commands(
        commands=admin_commands,
        scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID)
    )
    logger.info(f"Установлены расширенные команды для админа (ID: {ADMIN_CHAT_ID})")

def main():
    logger.info("🚦 Старт бота!")
    try:
        keep_alive()
        if TOKEN is None:
            logger.critical("TOKEN must not be None. Проверь config.py")
            raise ValueError("TOKEN must not be None. Please set the TOKEN in your config.")

        application = Application.builder().token(TOKEN).build()

SET_EMAIL = range(1)
from handlers.user_handlers import set_email_command, process_email, cancel_email

set_email_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("set_email", set_email_command)],
    states={
        SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]
    },
    fallbacks=[CommandHandler("cancel", cancel_email)],
)
application.add_handler(set_email_conv_handler)

        async def post_init(application):
            logger.info("Инициализация: запуск проверки почты и планировщика...")
            await start_mail_checking()
            start_scheduler(application.bot)
            await set_bot_commands(application)
            logger.info("Инициализация завершена.")

        application.post_init = post_init

        # ----------- Регистрируем хендлеры ------------
        application.add_handler(broadcast_conversation_handler)
        application.add_handler(tracking_conversation_handler())
        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("canceltracking", cancel))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))
        application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern="^cancel_tracking_"))
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ===
        application.add_error_handler(error_handler)

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