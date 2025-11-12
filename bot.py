# bot.py
import logging
from logger import get_logger
logger = get_logger(__name__)

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
# Добавляем импорт для обработки ошибки
from telegram.error import RetryAfter
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
# 1. 🐞 ИМПОРТИРУЕМ HTTPXRequest
from telegram.request import HTTPXRequest 
from dotenv import load_dotenv
load_dotenv()

# 2. 🐞 ИМПОРТИРУЕМ НАСТРОЙКУ ТАЙМАУТА
from config import TOKEN, ADMIN_CHAT_ID, TELEGRAM_SEND_TIMEOUT 
from scheduler import start_scheduler

# --- Пользовательские обработчики ---
from handlers.menu_handlers import start, reply_keyboard_handler, handle_sticker 
from handlers.email_management_handler import get_email_conversation_handler, get_email_command_handlers

from handlers.subscription_management_handler import (
    get_subscription_management_handlers, 
    get_add_containers_conversation_handler, # Для добавления
    get_remove_containers_conversation_handler # Для удаления
)

from handlers.tracking_handlers import tracking_conversation_handler
from handlers.dislocation_handlers import handle_message, handle_single_container_excel_callback 
from handlers.broadcast import broadcast_conversation_handler
from handlers.train import setup_handlers as setup_train_handlers
# --- ✅ ДОБАВЬТЕ ЭТОТ ИМПОРТ ---
from handlers.admin.event_email_handler import get_event_email_handlers
# ---

# ✅ НОВЫЙ ИМПОРТ для расчета расстояния
from handlers.distance_handlers import distance_conversation_handler

# --- Импорты для админ-панели ---
from handlers.admin.panel import admin_panel, admin_panel_callback
# --- ✅ ИЗМЕНЕННЫЙ ИМПОРТ ---
from handlers.admin.uploads import upload_file_command, get_admin_upload_conversation_handler
from handlers.admin.exports import stats, exportstats, tracking
from handlers.admin.notifications import force_notify_handler 

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
    admin_commands = user_commands + [
        BotCommand("admin", "Панель администратора"),
        BotCommand("stats", "Статистика за сутки"),
        BotCommand("broadcast", "Создать рассылку"),
        BotCommand("force_notify", "Принудительная рассылка"),
        BotCommand("train", "Отчёт по поезду"),
        BotCommand("upload_file", "Инструкция по загрузке файлов"),
        # --- ✅ ДОБАВЬТЕ ЭТУ КОМАНДУ ---
        BotCommand("event_emails", "Email для событий поезда")
        # ---
    ]
    
    try:
        await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
        logger.info("✅ Команды для пользователей и администратора установлены.")
    except RetryAfter as e:
        # Обрабатываем Flood Control: команды обновятся при следующей успешной попытке
        logger.warning(f"⚠️ Пропущена установка команд из-за Flood Control: {e}. Повторится позже.")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при установке команд: {e}")


def main():
    logger.info("🚦 Старт бота!")
    if not TOKEN:
        logger.critical("🔥 TELEGRAM_TOKEN не задан!")
        return

    logging.getLogger("httpx").setLevel(logging.WARNING) 
    
    # 3. 🐞 СОЗДАЕМ REQUEST С УВЕЛИЧЕННЫМ ТАЙМАУТОМ (Исправление TimedOut)
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=TELEGRAM_SEND_TIMEOUT, # 90.0 из config.py
        write_timeout=TELEGRAM_SEND_TIMEOUT, # 90.0 из config.py
    )
    
    # 4. 🐞 ПРИМЕНЯЕМ REQUEST К APPLICATION
    application = Application.builder().token(TOKEN).request(request).build()
    
    # --- 1. Диалоги (Группа 0 - высший приоритет) ---
    # Эти обработчики "слушают" первыми
    application.add_handler(broadcast_conversation_handler)
    application.add_handler(tracking_conversation_handler())
    application.add_handler(get_email_conversation_handler())
    setup_train_handlers(application)
    application.add_handler(distance_conversation_handler()) # <-- Вызываем функцию ()
    application.add_handler(get_add_containers_conversation_handler())
    application.add_handler(get_remove_containers_conversation_handler())
    
    # --- ✅ ДОБАВЬТЕ ЭТОТ ХЕНДЛЕР ---
    application.add_handlers(get_event_email_handlers())
    # ---
    
    # --- ✅ ДОБАВЛЕН НОВЫЙ ДИАЛОГ ЗАГРУЗКИ ---
    application.add_handler(get_admin_upload_conversation_handler())
    
    # --- 2. Команды (Группа 0) ---
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("upload_file", upload_file_command))
    application.add_handler(CommandHandler("force_notify", force_notify_handler))
    
    application.add_handler(CommandHandler("start", start))
    application.add_handlers(get_email_command_handlers())
    application.add_handlers(get_subscription_management_handlers())
    
    # --- 3. Колбэки (Группа 0) ---
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(handle_single_container_excel_callback, pattern="^get_excel_single_")) 
    
    # --- 4. Обработчики сообщений (Группа 0 и 1) ---
    # Этот обработчик кнопок меню (Regex) имеет приоритет 0 по умолчанию
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'(Дислокация|подписки|поезда|Настройки)'), 
        reply_keyboard_handler
    ))
    
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    # --- ❌ СТАРЫЙ ОБРАБОТЧИК УДАЛЕН ---
    # application.add_handler(MessageHandler(
    #     filters.Chat(ADMIN_CHAT_ID) & filters.Document.FileExtension("xlsx"), 
    #     handle_admin_document
    # ))
    
    # --- 5. 🐞 ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ "МОЛЧАЩЕГО" БОТА ---
    # Мы ставим этот "общий" обработчик в группу 1 (низший приоритет),
    # и он срабатывает ТОЛЬКО на текст, содержащий цифры (Regex(r'[\d]')).
    # Текст "хабаровск" (без цифр) он проигнорирует.
    application.add_handler(MessageHandler(
        filters.Regex(r'[\d]') & ~filters.COMMAND, 
        handle_message), 
        group=1 
    )
    
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        # --- Инициализация БД ---
        await init_db() 
        # ------------------------
        
        await set_bot_commands(app)
        
        # Получаем функцию немедленного запуска
        dislocation_check_on_start_func = start_scheduler(app.bot)
        
        if dislocation_check_on_start_func:
            logger.info("⚡️ Запуск немедленной проверки дислокации после старта...")
            
            await dislocation_check_on_start_func(app.bot) 
            
        logger.info("✅ Бот полностью настроен и запущен.")

    application.post_init = post_init
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()