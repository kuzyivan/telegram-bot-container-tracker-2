from dotenv import load_dotenv
from pathlib import Path
import os

# Явно грузим .env рядом с config.py
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

# Поддерживаем оба ключа на всякий случай
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TOKEN")

_admin_chat_id = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = int(_admin_chat_id) if (_admin_chat_id and _admin_chat_id.isdigit()) else None

RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.getenv("PORT", "10000"))