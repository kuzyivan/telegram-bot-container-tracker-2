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
from scheduler import start_scheduler
# Импортируем новый сервис для стартовой проверки
from services.terminal_importer import check_and_process_terminal_report

# --- Импорты хендлеров ---
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
    """Логирует все необработанные ошибки."""
    logger.error("❗️Произошла необработанная ошибка: %s", context.error, exc_info=True)


async def debug_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладочный обработчик для логирования всех входящих апдейтов."""
    try:
        user = update.effective_user
        uid = user.id if user else "—"
        uname = user.username if user else "—"
        txt = getattr(getattr(update, "message", None), "text", None)
        logger.info(f"[DEBUG UPDATE] from {uid} (@{uname}) type={type(update).__name__} text='{txt}'")
    except Exception:
        logger.exception("[DEBUG UPDATE] не удалось залогировать апдейт")


async def set_bot_commands(application: Application):
    """Устанавливает команды в меню Telegram для обычных пользователей и администратора."""
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Показать главное меню"),
        BotCommand("canceltracking", "Отменить все слежения"),
        BotCommand("set_email", "Указать/изменить e-mail для отчётов"),
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Команды для пользователей установлены.")

    admin_commands = user_commands + [
        BotCommand("stats", "Статистика за сутки (админ)"),
        BotCommand("exportstats", "Выгрузить всю статистику (админ)"),
        BotCommand("testnotify", "Тестовая рассылка по всем (админ)"),
        BotCommand("tracking", "Выгрузить все подписки (админ)"),
        BotCommand("broadcast", "Рассылка всем пользователям (админ)"),
        BotCommand("train", "Отчёт по поезду (админ)"),
        BotCommand("upload_train", "Загрузить Excel поезда (админ)"),
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Команды для админа (ID: {ADMIN_CHAT_ID}) установлены.")


def main():
    """Основная функция для запуска бота."""
    logger.info("🚦 Старт бота!")
    
    if not TOKEN:
        logger.critical("🔥 Критическая ошибка: TELEGRAM_TOKEN не задан! Бот не может запуститься.")
        return

    try:
        request = HTTPXRequest(
            connect_timeout=20.0,
            read_timeout=60.0,
            write_timeout=60.0,
            pool_timeout=20.0,
            connection_pool_size=50,
        )
        application = Application.builder().token(TOKEN).request(request).build()

        # --- Регистрация обработчиков ---
        
        # Диалоги (Conversation Handlers)
        set_email_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("set_email", set_email_command)],
            states={SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]},
            fallbacks=[CommandHandler("cancel", cancel_email)],
        )
        application.add_handler(set_email_conv_handler)
        application.add_handler(broadcast_conversation_handler)
        application.add_handler(tracking_conversation_handler())
        setup_train_handlers(application)

        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(CommandHandler("canceltracking", cancel_my_tracking))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))
        application.add_handler(CommandHandler("upload_train", upload_train_help))
        
        # Обработчики Callback-кнопок
        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
        application.add_handler(CallbackQueryHandler(cancel_tracking_start, pattern=r"^cancel_tracking$"))
        application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern=r"^cancel_tracking_(yes|no)$"))

        # Обработчики сообщений
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_train_excel))
        
        # Этот обработчик должен быть одним из последних, так как он ловит любой текст
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Отладочный обработчик (ловит вообще всё, что не было поймано ранее)
        application.add_handler(MessageHandler(filters.ALL, debug_all_updates))

        # Глобальный обработчик ошибок
        application.add_error_handler(error_handler)

        async def post_init(app: Application):
            """Выполняется после инициализации приложения, перед запуском polling."""
            logger.info("⚙️ Запускаем задачи после инициализации...")
            try:
                await app.bot.send_message(ADMIN_CHAT_ID, "🤖 Бот стартовал (с разделенными задачами).")
                me = await app.bot.get_me()
                logger.info(f"Успешный getMe: @{me.username} (id={me.id})")
            except Exception as e:
                logger.error(f"Не смог отправить стартовое сообщение админу: {e}", exc_info=True)

            # При старте запускаем импорт отчета терминала, чтобы получить актуальную базу,
            # если бот был выключен во время планового запуска.
            logger.info("Запускаю стартовую проверку отчета терминала...")
            await check_and_process_terminal_report()
            
            # Запускаем планировщик
            start_scheduler(app.bot)
            
            # Устанавливаем команды в меню
            await set_bot_commands(app)
            logger.info("✅ post_init завершён.")

        application.post_init = post_init
        
        logger.info("🤖 Бот готов к запуску. Начинаю polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.critical("🔥 Критическая ошибка при запуске бота: %s", e, exc_info=True)


if __name__ == "__main__":
    main()