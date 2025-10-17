# handlers/train_handlers.py
# Этот файл больше не обрабатывает документы и не регистрирует команды.
# Вся логика ручной загрузки централизована в admin_handlers.py.

from __future__ import annotations
from pathlib import Path
from telegram.ext import Application
from logger import get_logger

logger = get_logger(__name__)

# Папка для файлов остается, так как она может использоваться другими сервисами.
DOWNLOAD_DIR = Path("/root/AtermTrackBot/download_train")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Все функции-обработчики (`CommandHandler`, `MessageHandler`) отсюда удалены,
# так как они теперь находятся в `admin_handlers.py` и регистрируются в `bot.py`.

def register_train_handlers(app: Application) -> None:
    """
    Эта функция больше не нужна, так как обработчики регистрируются напрямую в bot.py.
    Оставлена пустой для обратной совместимости, если где-то остался ее вызов.
    """
    pass