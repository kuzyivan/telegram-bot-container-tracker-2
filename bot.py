from logger import get_logger
logger = get_logger(__name__)

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
)
from dotenv import load_dotenv
load_dotenv()  # опционально; при запуске через systemd берётся EnvironmentFile

from config import TOKEN, ADMIN_CHAT_ID
from mail_reader import start_mail_checking
from scheduler import start_scheduler

# --- разнесённые хендлеры ---
# email
from handlers.email_handlers import set_email_command, process_email, cancel_email, SET_EMAIL
# меню, кнопки, стикеры
from handlers.menu_handlers import (
    start, show_menu, reply_keyboard_handler,
    menu_button_handler, dislocation_inline_callback_handler, handle_sticker
)
# поиск/вывод дислокации
from handlers.dislocation_handlers import handle_message
# админка
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
# трекинг контейнеров
from handlers.tracking_handlers import (
    tracking_conversation_handler,
    cancel,
    cancel_tracking_confirm
)
# рассылка
from handlers.broadcast import broadcast_conversation_handler
# ПОЕЗДА: загрузка Excel с номером поезда из имени файла
from handlers.train_handlers import upload_train_help, handle_train_excel


# === ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ===
async def error_handler(update, context):
    logger.error("❗️Произошла необработанная ошибка: %s", context.error, exc_info=True)


# === ЛОВЕЦ ЛЮБЫХ АПДЕЙТОВ ДЛЯ ДЕБАГА ===
async def debug_all_updates(update: Update, context):
    try:
        uid = update.effective_user.id if update.effective_user else "—"
        uname = update.effective_user.username if update.effective_user else "—"
        txt = getattr(getattr(update, "message", None), "text", None)
        logger.info(f"[DEBUG UPDATE] from {uid} (@{uname}) type={type(update).__name__} text={txt}")
    except Exception:
        logger.exception("[DEBUG UPDATE] failed to log update")


# === УСТАНОВКА КОМАНД ===
async def set_bot_commands(application):
    user_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("canceltracking", "Отменить все слежения"),
        BotCommand("set_email", "Указать e-mail для отчётов"),
        BotCommand("email_off", "Отключить рассылку на e-mail"),
        # Подсказка по загрузке поездов (для всех, обработает всё равно только админ)
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
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Команды для админа (ID: {ADMIN_CHAT_ID}) установлены.")


# === ОСНОВНАЯ ФУНКЦИЯ ===
def main():
    logger.info("🚦 Старт бота!")
    try:
        application = Application.builder().token(TOKEN).build()

        # === ConversationHandler для /set_email ===
        set_email_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("set_email", set_email_command)],
            states={SET_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_email)]},
            fallbacks=[CommandHandler("cancel", cancel_email)],
        )
        application.add_handler(set_email_conv_handler)

        # === Хендлеры ===
        application.add_handler(broadcast_conversation_handler)
        application.add_handler(tracking_conversation_handler())

        # Callback-кнопки
        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))
        application.add_handler(CallbackQueryHandler(cancel_tracking_confirm, pattern="^cancel_tracking_"))

        # Команды
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("canceltracking", cancel))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))

        # Подсказка по загрузке поездов (сообщение с инструкцией)
        application.add_handler(CommandHandler("upload_train", upload_train_help))

        # Приём Excel-файлов с поездами от админа.
        # Берём любой документ, тип/расширение проверяем внутри handle_train_excel.
        application.add_handler(
            MessageHandler(
                filters.Document.ALL,
                handle_train_excel
            )
        )

        # Reply-кнопки главного меню
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))

        # Стикеры
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

        # Любой прочий текст — поиск дислокации
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Самый последний — отладочный ловец любых апдейтов
        application.add_handler(MessageHandler(filters.ALL, debug_all_updates))

        # === Обработчик ошибок ===
        application.add_error_handler(error_handler)

        # === post_init с задачами ===
        async def post_init(app):
            logger.info("⚙️ Запускаем фоновую проверку почты и планировщик...")

            # Пинг админу + getMe для явной проверки токена/доставки
            try:
                await app.bot.send_message(ADMIN_CHAT_ID, "🤖 Бот стартовал и слушает апдейты (polling).")
                me = await app.bot.get_me()
                logger.info(f"getMe: @{me.username} (id={me.id})")
            except Exception as e:
                logger.error(f"Не смог отправить стартовое сообщение админу: {e}", exc_info=True)

            await start_mail_checking()
            start_scheduler(app.bot)
            await set_bot_commands(app)
            logger.info("✅ post_init завершён.")

        application.post_init = post_init

        logger.info("🤖 Бот готов к запуску. Запускаем polling...")
        application.run_polling(
            allowed_updates=None,       # брать все типы апдейтов
            drop_pending_updates=False, # не отбрасывать накопленные новые апдейты
            stop_signals=None,          # корректно завершится по SIGTERM от systemd
            close_loop=False
        )
        logger.info("✅ Бот завершил работу.")

    except Exception as e:
        logger.critical("🔥 Критическая ошибка при запуске бота: %s", e, exc_info=True)


if __name__ == "__main__":
    main()