import logging
import traceback
import html
import json
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
# keep_alive больше не используется, так как Render не требует этого.
# from utils.keep_alive import keep_alive 
from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from handlers.tracking_handlers import (
    tracking_conversation_handler,
    cancel_tracking,
    cancel_tracking_confirm
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Глобальный обработчик ошибок.
    Логирует все исключения и отправляет полное сообщение об ошибке администратору.
    """
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Собираем traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Форматируем сообщение для отправки
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"Произошла непредвиденная ошибка\n\n"
        f"<b>Update:</b>\n<pre>{html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<b>Context.chat_data:</b>\n<pre>{html.escape(str(context.chat_data))}</pre>\n\n"
        f"<b>Context.user_data:</b>\n<pre>{html.escape(str(context.user_data))}</pre>\n\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(tb_string)}</pre>"
    )

    # Отправляем сообщение администратору, разбивая на части, если оно слишком длинное
    for i in range(0, len(message), 4096):
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=message[i:i+4096], parse_mode='HTML'
        )

async def set_bot_commands(application: Application):
    """Устанавливает команды, видимые в меню Telegram."""
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 Запустить бота / Главное меню"),
        BotCommand("menu", "📋 Главное меню"),
        BotCommand("canceltracking", "❌ Отменить все слежения"),
        BotCommand("stats", "📊 Статистика (админ)"),
        BotCommand("exportstats", "📥 Выгрузка статистики (админ)"),
        BotCommand("testnotify", "🔔 Тестовая рассылка (админ)"),
    ])

def main():
    # keep_alive() # Render не требует этого
    
    application = Application.builder().token(TOKEN).build()

    # ДОБАВЛЕН ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        """Выполняется после инициализации приложения."""
        await start_mail_checking()
        start_scheduler(app.bot)
        await set_bot_commands(app)
    
    application.post_init = post_init

    # ConversationHandler для отслеживания должен быть зарегистрирован одним из первых
    application.add_handler(tracking_conversation_handler())
    
    # Обработчики CallbackQueryHandler (нажатия на inline-кнопки)
    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
    application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
    application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern="^cancel_tracking_"))

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("canceltracking", cancel_tracking))
    
    # Админские команды
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))

    # Обработчик Reply-клавиатуры
    application.add_handler(MessageHandler(
        filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
        reply_keyboard_handler
    ))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    # Обработчик текстовых сообщений должен быть одним из последних
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✨ Бот запущен!")

    # Запуск в режиме вебхуков для Render
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
