# telegram_bot.py

import os
import logging
from telegram import Update # <-- ИСПРАВЛЕНИЕ: ДОБАВЛЕН ИМПОРТ UPDATE
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ConversationHandler
)
from dotenv import load_dotenv

load_dotenv()

from core.data_loader import load_kniga_2_rp, load_kniga_3_matrices
from core.data_parser import normalize_station_name
from bot import ui, handlers

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DATA_DIR = './data'

async def post_init(application: Application) -> None:
    """Загружает и подготавливает данные после старта бота."""
    logger.info("Загрузка данных...")
    df_stations = load_kniga_2_rp(DATA_DIR)
    transit_matrices = load_kniga_3_matrices(DATA_DIR)
    
    if df_stations is None or not transit_matrices:
        logger.critical("Не удалось загрузить все необходимые данные!")
    else:
        logger.info("Данные загружены. Создание индекса для гибкого поиска...")
        application.bot_data['df_stations'] = df_stations
        application.bot_data['transit_matrices'] = transit_matrices
        df_stations['normalized_name'] = df_stations['station_name'].apply(normalize_station_name)
        logger.info("Индекс для гибкого поиска создан. Бот готов к работе.")

def main() -> None:
    """Собирает и запускает бота."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") 
    if not token:
        logger.critical("TELEGRAM_BOT_TOKEN не найден в .env файле!")
        exit(1)

    application = Application.builder().token(token).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", handlers.start)],
        states={
            ui.MAIN_MENU_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_main_menu_choice)],
            ui.ASKING_FROM_STATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.ask_from_station),
                CallbackQueryHandler(handlers.ask_from_station)
            ],
            ui.ASKING_TO_STATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.ask_to_station),
                CallbackQueryHandler(handlers.ask_to_station)
            ],
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", handlers.help_command))

    print("Бот запущен! Ожидаю сообщений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()