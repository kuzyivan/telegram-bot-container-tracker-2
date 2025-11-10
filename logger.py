import logging
from logging.handlers import RotatingFileHandler
import os
from pythonjsonlogger import jsonlogger # <-- Импортируем jsonlogger
from typing import Optional

LOG_DIR = "logs"
LOG_FILE = "bot.log"
os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name: Optional[str] = None):
    logger = logging.getLogger(name)
    if not logger.hasHandlers():

        # --- 1. Настраиваем JSON-форматтер ---
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(levelname)s %(module)s %(lineno)d %(message)s',
            rename_fields={"levelname": "level", "asctime": "timestamp"},
            json_ensure_ascii=False  # <-- ДОБАВЬТЕ ЭТУ СТРОКУ
        )
        # -----------------------------------

        # --- 2. Оставляем ваш RotatingFileHandler ---
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, LOG_FILE),
            maxBytes=5*1024*1024,  # 5 МБ
            backupCount=5,
            encoding="utf-8"
        )

        handler.setFormatter(formatter) # <-- Применяем JSON-форматтер
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # --- 3. (Опционально) Оставляем вывод в консоль для отладки ---
        stream = logging.StreamHandler()
        stream.setFormatter(formatter) # <-- Тоже в JSON
        logger.addHandler(stream)

    return logger