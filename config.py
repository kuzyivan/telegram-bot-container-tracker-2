import os
from dotenv import load_dotenv
from logger import get_logger

logger = get_logger(__name__)

# === Загружаем переменные из .env ===
load_dotenv()

# === Обязательные переменные ===
DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not all([DATABASE_URL, TOKEN, ADMIN_CHAT_ID]):
    logger.critical("❌ Обязательные переменные не заданы! Проверь .env файл.")
    raise RuntimeError("Невозможно запустить бота: переменные окружения не заданы.")

# Преобразуем ADMIN_CHAT_ID
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    logger.critical("❌ ADMIN_CHAT_ID должен быть числом.")
    raise

# === Дополнительные переменные с дефолтами ===
PORT = int(os.getenv("PORT", 10000))
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

# 🔐 SMTP логин и пароль
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)

# Проверка критичных для почты
if not SMTP_USER or not SMTP_PASS:
    logger.warning("⚠️ SMTP_USER или SMTP_PASS не заданы — e-mail рассылка работать не будет.")