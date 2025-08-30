# bot.py
from logger import get_logger
logger = get_logger(__name__)

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler, ContextTypes
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
load_dotenv()

from config import TOKEN, ADMIN_CHAT_ID
# ИСПРАВЛЕНИЕ 1: Импортируем 'check_mail' вместо 'start_mail_checking'
from mail_reader import check_mail
from scheduler import start_scheduler

# --- разнесённые хендлеры ---
from handlers.email_handlers import set_email_command, process_email, cancel_email, SET_EMAIL
from handlers.menu_handlers import (
    start, show_menu, reply_keyboard_handler,
    menu_button_handler, dislocation_inline_callback_handler, handle_sticker
)
from handlers.dislocation_handlers import handle_message
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from handlers.tracking_handlers import (
    tracking_conversation_handler,
    cancel_tracking_start,
    cancel_tracking_confirm,
)
from handlers.misc_handlers import cancel_my_tracking
from handlers.broadcast import broadcast_conversation_handler
from handlers.train_handlers import upload_train_help, handle_train_excel
from handlers.train import setup_handlers as setup_train_handlers


async def error_handler(update, context):
    logger.error("❗️Произошла необработанная ошибка: %s", context.error, exc_info=True)


async def debug_all_updates(update: Update, context):
    try:
        uid = update.effective_user.id if update.effective_user else "—"
        uname = update.effective_user.username if update.effective_user else "—"
        txt = getattr(getattr(update, "message", None), "text", None)
        logger.info(f"[DEBUG UPDATE] from {uid} (@{uname}) type={type(update).__name__} text={txt}")
    except Exception:
        logger.exception("[DEBUG UPDATE] failed to log update")


async def set_bot_commands(application):
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("canceltracking", "Отменить все слежения"),
        BotCommand("set_email", "Указать e-mail для отчётов"),
        BotCommand("email_off", "Отключить рассылку на e-mail"),
        BotCommand("upload_train", "Загрузить Excel с поездами"),
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Команды для пользователей установлены.")

    admin_commands = user_commands + [
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)"),
        BotCommand("tracking", "Выгрузка подписок (админ)"),
        BotCommand("broadcast", "Рассылка (админ)"),
        BotCommand("train", "Отчёт по поезду (админ)"),
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Команды для админа (ID: {ADMIN_CHAT_ID}) установлены.")


def main():
    logger.info("🚦 Старт бота!")
    
    # ИСПРАВЛЕНИЕ 2: Добавляем проверку наличия токена перед запуском
    if not TOKEN:
        logger.critical("🔥 Критическая ошибка: TELEGRAM_TOKEN не задан! Бот не может запуститься.")
        return  # Прерываем выполнение, если токена нет

    try:
        request = HTTPXRequest(
            connect_timeout=20.0,
            read_timeout=60.0,
            write_timeout=60.0,
            pool_timeout=20.0,
            connection_pool_size=50,
        )
        application = Application.builder().token(TOKEN).request(request).build()

        set_email_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("set_email", set_email_command)],
            states={SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]},
            fallbacks=[CommandHandler("cancel", cancel_email)],
        )
        application.add_handler(set_email_conv_handler)
        
        application.add_handler(broadcast_conversation_handler)
        application.add_handler(tracking_conversation_handler())

        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
        application.add_handler(CallbackQueryHandler(cancel_tracking_start, pattern=r"^cancel_tracking$"))
        application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern=r"^cancel_tracking_(yes|no)$"))

        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("canceltracking", cancel_my_tracking))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))
        setup_train_handlers(application)
        logger.info("✅ /train зарегистрирован (handlers.train)")

        application.add_handler(CommandHandler("upload_train", upload_train_help))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_train_excel))
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.ALL, debug_all_updates))

        application.add_error_handler(error_handler)

        async def post_init(app):
            logger.info("⚙️ Запускаем фоновую проверку почты и планировщик...")

            try:
                await app.bot.send_message(ADMIN_CHAT_ID, "🤖 Бот стартовал и слушает апдейты (polling).")
                me = await app.bot.get_me()
                logger.info(f"getMe: @{me.username} (id={me.id})")
            except Exception as e:
                logger.error(f"Не смог отправить стартовое сообщение админу: {e}", exc_info=True)

            # ИСПРАВЛЕНИЕ 1 (продолжение): Вызываем 'check_mail'
            await check_mail()
            start_scheduler(app.bot)
            await set_bot_commands(app)
            logger.info("✅ post_init завершён.")

        application.post_init = post_init

        logger.info("🤖 Бот готов к запуску. Запускаем polling...")
        application.run_polling(
            allowed_updates=None,
            drop_pending_updates=False,
            stop_signals=None,
            close_loop=False
        )
        logger.info("✅ Бот завершил работу.")

    except Exception as e:
        logger.critical("🔥 Критическая ошибка при запуске бота: %s", e, exc_info=True)


if __name__ == "__main__":
    main()