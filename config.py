import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get("PORT", 10000))
