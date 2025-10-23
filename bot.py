# bot.py
import logging
from logger import get_logger
logger = get_logger(__name__)

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
load_dotenv()

from config import TOKEN, ADMIN_CHAT_ID
from scheduler import start_scheduler

# --- Пользовательские обработчики ---
from handlers.menu_handlers import start, reply_keyboard_handler, handle_sticker 
from handlers.email_management_handler import get_email_conversation_handler, get_email_command_handlers
from handlers.subscription_management_handler import get_subscription_management_handlers
from handlers.tracking_handlers import tracking_conversation_handler
# ✅ НОВЫЙ ИМПОРТ: handle_single_container_excel_callback
from handlers.dislocation_handlers import handle_message, handle_single_container_excel_callback 
from handlers.broadcast import broadcast_conversation_handler
from handlers.train import setup_handlers as setup_train_handlers

# ✅ НОВЫЙ ИМПОРТ для расчета расстояния
from handlers.distance_handlers import distance_conversation_handler

# --- Импорты для админ-панели ---
from handlers.admin.panel import admin_panel, admin_panel_callback
from handlers.admin.uploads import upload_file_command, handle_admin_document
from handlers.admin.exports import stats, exportstats, tracking
from handlers.admin.notifications import force_notify_handler # <--- НОВЫЙ ИМПОРТ

# --- ИМПОРТ init_db ---
from db import init_db
# ---------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех необработанных ошибок."""
    logger.error("❗️ Ошибка: %s", context.error, exc_info=True)

async def set_bot_commands(application: Application):
    """Устанавливает команды для бота."""
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("distance", "Расчет расстояния Прейскурант 10-01"),
        BotCommand("my_emails", "Мои Email-адреса"),
        BotCommand("my_subscriptions", "Мои подписки")
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    
    admin_commands = user_commands + [
        BotCommand("admin", "Панель администратора"),
        BotCommand("stats", "Статистика за сутки"),
        BotCommand("broadcast", "Создать рассылку"),
        BotCommand("force_notify", "Принудительная рассылка"),
        BotCommand("train", "Отчёт по поезду"),
        BotCommand("upload_file", "Инструкция по загрузке файлов")
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info("✅ Команды для пользователей и администратора установлены.")

def main():
    logger.info("🚦 Старт бота!")
    if not TOKEN:
        logger.critical("🔥 TELEGRAM_TOKEN не задан!")
        return

    logging.getLogger("httpx").setLevel(logging.WARNING) 
    
    application = Application.builder().token(TOKEN).build()
    
    # 1. Диалоги
    application.add_handler(broadcast_conversation_handler)
    application.add_handler(tracking_conversation_handler())
    application.add_handler(get_email_conversation_handler())
    setup_train_handlers(application)
    application.add_handler(distance_conversation_handler())
    
    # 2. Команды админа
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("upload_file", upload_file_command))
    application.add_handler(CommandHandler("force_notify", force_notify_handler)) # <--- РЕГИСТРАЦИЯ НОВОЙ КОМАНДЫ
    
    # 3. Команды пользователя
    application.add_handler(CommandHandler("start", start))
    application.add_handlers(get_email_command_handlers())
    application.add_handlers(get_subscription_management_handlers())
    
    # 4. Колбэки
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    # ✅ РЕГИСТРАЦИЯ НОВОГО ОБРАБОТЧИКА: для кнопки скачивания Excel
    application.add_handler(CallbackQueryHandler(handle_single_container_excel_callback, pattern="^get_excel_single_")) 
    
    # 5. Обработчики сообщений
    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ REGEX: Упрощаем до ключевых слов для надежности
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'(Дислокация|подписки|поезда|Настройки)'), 
        reply_keyboard_handler
    ))
    
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(
        filters.Chat(ADMIN_CHAT_ID) & filters.Document.FileExtension("xlsx"), 
        handle_admin_document
    ))
    # Общий обработчик текста идет последним
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        # --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ ---
        await init_db() # Гарантируем, что все таблицы существуют перед запуском
        # -----------------------------
        
        await set_bot_commands(app)
        
        dislocation_check_on_start_func = start_scheduler(app.bot)
        
        if dislocation_check_on_start_func:
            logger.info("⚡️ Запуск немедленной проверки дислокации после старта...")
            await dislocation_check_on_start_func()
            
        logger.info("✅ Бот полностью настроен и запущен.")

    application.post_init = post_init
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
