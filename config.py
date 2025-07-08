from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) # type: ignore
PORT = int(os.environ.get("PORT", 10000))
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "bottrack@yandex.ru")
SMTP_PASS = os.getenv("SMTP_PASS", "пароль_от_почты")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)