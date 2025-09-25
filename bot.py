# bot.py
from logger import get_logger
logger = get_logger(__name__)

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
load_dotenv()

# --- Конфигурация и сервисы ---
from config import TOKEN, ADMIN_CHAT_ID
from scheduler import start_scheduler

# --- Обработчики ---
from handlers.menu_handlers import start, reply_keyboard_handler, handle_sticker
from handlers.email_management_handler import get_email_conversation_handler, get_email_command_handlers
from handlers.subscription_management_handler import get_subscription_management_handlers
from handlers.tracking_handlers import tracking_conversation_handler
from handlers.dislocation_handlers import handle_message
from handlers.admin_handlers import stats, exportstats, tracking, test_notify, force_notify
from handlers.broadcast import broadcast_conversation_handler
from handlers.train_handlers import upload_train_help, handle_train_excel
# V--- НОВЫЙ ИМПОРТ ---V
from handlers.train import setup_handlers as setup_train_handlers

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("❗️ Произошла необработанная ошибка: %s", context.error, exc_info=True)

async def set_bot_commands(application: Application):
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("my_emails", "Управление Email-адресами"),
        BotCommand("my_subscriptions", "Мои подписки")
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Команды для пользователей установлены.")
    
    admin_commands = user_commands + [
        BotCommand("stats", "Статистика за сутки"),
        BotCommand("exportstats", "Выгрузить всю статистику"),
        BotCommand("tracking", "Выгрузить все подписки"),
        BotCommand("testnotify", "Тестовая рассылка"),
        BotCommand("force_notify", "Принудительная рассылка"),
        BotCommand("broadcast", "Рассылка всем"),
        BotCommand("train", "Отчёт по поезду"),
        BotCommand("upload_train", "Загрузить Excel поезда")
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Команды для админа (ID: {ADMIN_CHAT_ID}) установлены.")

def main():
    logger.info("🚦 Старт бота!")
    if not TOKEN:
        logger.critical("🔥 Критическая ошибка: TELEGRAM_TOKEN не задан!")
        return

    # Устанавливаем таймауты для работы с медленным OSM API
    request = HTTPXRequest(connect_timeout=10.0, read_timeout=60.0, write_timeout=60.0, pool_timeout=60.0)
    
    application = Application.builder().token(TOKEN).request(request).build()
    
    # --- Регистрация обработчиков ---
    
    # 1. Диалоги (ConversationHandlers)
    application.add_handler(broadcast_conversation_handler)
    application.add_handler(tracking_conversation_handler())
    application.add_handler(get_email_conversation_handler())
    # V--- НОВАЯ РЕГИСТРАЦИЯ ---V
    setup_train_handlers(application) # Регистрирует диалог для команды /train
    
    # 2. Обработчики команд и колбэков
    application.add_handlers(get_email_command_handlers())
    application.add_handlers(get_subscription_management_handlers())
    
    application.add_handler(CommandHandler("start", start))
    
    # Команды админа
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))
    application.add_handler(CommandHandler("force_notify", force_notify))
    application.add_handler(CommandHandler("upload_train", upload_train_help))
    
    # 3. Обработчики сообщений (от частных к общим)
    application.add_handler(MessageHandler(filters.Regex("^(📦 Дислокация|📂 Мои подписки)$"), reply_keyboard_handler))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.Document.FileExtension("xlsx"), handle_train_excel))
    
    # Общий текстовый обработчик для поиска контейнеров (должен быть одним из последних)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        await set_bot_commands(app)
        start_scheduler(app.bot)
        logger.info("✅ Бот полностью настроен и запущен.")

    application.post_init = post_init
    
    logger.info("🤖 Начинаю polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()