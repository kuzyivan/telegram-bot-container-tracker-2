# bot.py
import asyncio
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
from telegram.ext._updater import Updater
from dotenv import load_dotenv
load_dotenv()

# 2. 🐞 ИМПОРТИРУЕМ НАСТРОЙКУ ТАЙМАУТА
from config import TOKEN, ADMIN_CHAT_ID, TELEGRAM_SEND_TIMEOUT, WEBHOOK_HOST, WEBHOOK_PATH, WEBHOOK_PORT
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
        connection_pool_size=8,  # Prevent PoolTimeout when concurrent API calls happen at startup
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
    
    # --- 4. Обработчики сообщений ---
    
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    # --- ⭐️ ИЗМЕНЕНИЕ ЗДЕСЬ ⭐️ ---
    
    # УДАЛЯЕМ СТАРЫЙ ОБРАБОТЧИК КНОПОК:
    # application.add_handler(MessageHandler(
    #     filters.TEXT & filters.Regex(r'(Дислокация|подписки|поезда|Настройки)'), 
    #     reply_keyboard_handler
    # ))
    
    # УДАЛЯЕМ СТАРЫЙ ОБРАБОТЧИК ДИСЛОКАЦИИ:
    # application.add_handler(MessageHandler(
    #     filters.Regex(r'[\d]') & ~filters.COMMAND, 
    #     handle_message), 
    #     group=1 
    # )

    # ДОБАВЛЯЕМ НОВЫЙ ЕДИНЫЙ ДИСПЕТЧЕР ТЕКСТА (в группу 1, чтобы не мешать диалогам)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        reply_keyboard_handler), 
        group=1 
    )
    # --- ⭐️ КОНЕЦ ИЗМЕНЕНИЙ ⭐️ ---
    
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        # --- Инициализация БД ---
        await init_db() 
        # ------------------------
        
        asyncio.create_task(set_bot_commands(app))

        # Получаем функцию немедленного запуска
        dislocation_check_on_start_func = start_scheduler(app.bot)
        
        if dislocation_check_on_start_func:
            logger.info("⚡️ Запуск проверки дислокации в фоне (не блокирует старт)...")
            asyncio.create_task(dislocation_check_on_start_func(app.bot))

        logger.info("✅ Бот полностью настроен и запущен.")

    application.post_init = post_init
    
    application.run_webhook(
        listen="127.0.0.1",
        port=WEBHOOK_PORT,
        url_path=WEBHOOK_PATH,
        allowed_updates=Update.ALL_TYPES,
    )

async def _noop_bootstrap(self, *args, **kwargs):
    """Skip PTB's setWebhook API call — webhook is managed externally via curl/API."""
    pass

_original_app_start = Application.start

async def _patched_app_start(self, *args, **kwargs):
    """Fix PTB 22.1 bug: _initialized=True is set before get_me() succeeds.
    On TimedOut, subsequent initialize() calls are no-ops, leaving _bot_user=None."""
    if self.bot._bot_user is None:
        logger.warning("⚠️ bot._bot_user is None before start() — retrying get_me()...")
        for attempt in range(5):
            try:
                self.bot._initialized = False
                await self.bot.initialize()
                logger.info("✅ bot re-initialized OK")
                break
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"Re-init attempt {attempt+1}/5 failed: {e}. Waiting {wait}s...")
                await asyncio.sleep(wait)
        else:
            logger.critical("❌ Could not re-initialize bot after 5 attempts. Giving up.")
            raise RuntimeError("Bot initialization failed: get_me() never succeeded")
    return await _original_app_start(self, *args, **kwargs)

Updater._bootstrap = _noop_bootstrap
Application.start = _patched_app_start

if __name__ == "__main__":
    main()