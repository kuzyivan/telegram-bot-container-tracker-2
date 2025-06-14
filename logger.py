# logger.py
import logging
from logging.handlers import RotatingFileHandler
import os

LOG_DIR = "logs"
LOG_FILE = "bot.log"
os.makedirs(LOG_DIR, exist_ok=True)

from typing import Optional

def get_logger(name: Optional[str] = None):
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s [%(module)s:%(lineno)d] %(message)s'
        )
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, LOG_FILE),
            maxBytes=5*1024*1024,  # 5 МБ на файл, потом лог будет ротироваться
            backupCount=5,         # хранить 5 старых файлов логов
            encoding="utf-8"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # Дополнительно, чтобы видеть логи в консоли при отладке:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger