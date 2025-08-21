from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Database connection URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Telegram bot token (support both TOKEN and TELEGRAM_TOKEN)
TOKEN = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN")

# Admin chat ID (optional, safe cast to int if provided)
_admin_chat_id = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = int(_admin_chat_id) if _admin_chat_id else None

# Render (or VDS) host settings
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

# Port (default to 10000 if not set)
PORT = int(os.getenv("PORT", 10000))