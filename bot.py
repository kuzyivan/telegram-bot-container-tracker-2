import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from telegram import BotCommand

from config import TOKEN, ADMIN_CHAT_ID, RENDER_HOSTNAME, PORT
from mail_reader import start_mail_checking
from scheduler import start_scheduler
from utils.keep_alive import keep_alive
from handlers.user_handlers import (
    start, handle_sticker, handle_message, show_menu,
    menu_button_handler, reply_keyboard_handler, dislocation_inline_callback_handler
)
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from db import SessionLocal
from handlers.tracking_handlers import tracking_conversation_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Главное меню"),
        BotCommand("stats", "Статистика (админ)"),
        BotCommand("exportstats", "Выгрузка (админ)"),
        BotCommand("testnotify", "Тестовая рассылка (админ)")
    ])

def main():
    start_mail_checking()
    keep_alive()

    application = Application.builder().token(TOKEN).build()

    async def post_init(application):
        start_scheduler(application.bot)
        await set_bot_commands(application)
    application.post_init = post_init

    # Inline-кнопки — всегда выше!
    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
    application.add_handler(CallbackQueryHandler(tracking_conversation_handler(), pattern="^track_request$"))
    application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))

    # Команды
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("start", start))

    # ReplyKeyboard обработчик
    application.add_handler(MessageHandler(
        filters.Regex("^(📦 Дислокация|🔔 Задать слежение)$"),
        reply_keyboard_handler
    ))

    # Остальные обработчики
    application.add_handler(tracking_conversation_handler())
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("testnotify", test_notify))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))  # В САМОМ КОНЦЕ!

    logger.info("✨ Бот запущен!")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{RENDER_HOSTNAME}/{TOKEN}",
    )

if __name__ == "__main__":
    main()
# This code is the main entry point for the Telegram bot.
# It initializes the bot, sets up command handlers, and starts the webhook.
# It also includes the scheduler for periodic tasks and mail checking.
# The bot handles user commands, inline queries, and replies to messages.
# It uses the Telegram Bot API and the application framework to manage updates and interactions.
# The bot is designed to provide container tracking and dislocation information.
#     track.current_station,
#                         track.operation,
#                         track.operation_date,
#                         track.waybill,
#                         track.km_left,
#                         track.forecast_days,
#                         track.wagon_number,
#                         track.operation_road
#                     ])
#             if not rows:
#                 await bot.send_message(sub.user_id, f"📭 Нет данных по контейнерам {', '.join(sub.containers)}"
#                 continue
#             file_path = create_excel_file(rows, columns)
#             filename = get_vladivostok_filename()
#             with open(file_path, "rb") as f:
#                 await bot.send_document(
#                     chat_id=sub.user_id,
#                     document=f,
#                     filename=filename
#                 )
#             data_per_user[user_label] = rows
#         file_path = create_excel_multisheet(data_per_user, columns)
#         filename = get_vladivostok_filename("Тестовая дислокация")
#         await update.message.reply_document(
#             document=open(file_path, "rb"),
#             filename=filename
#         )
#     )

    logger.info("🕓 Планировщик: задачи запущены.")
    logger.info("🌐 Вебхук настроен на URL: %s", f"https://{RENDER_HOSTNAME}/{TOKEN}")
    logger.info("🚀 Бот готов к работе на порту %d", PORT)
    logger.info("🔗 Бот запущен на хосте: %s", RENDER_HOSTNAME)
    logger.info("🔗 Бот запущен на порту: %d", PORT)
    