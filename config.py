# config.py
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) # type: ignore
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get("PORT", 10000))
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
# =========================
# Настройки уведомлений
# =========================
TRACKING_REPORT_COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]
TELEGRAM_SEND_ATTEMPTS = 3
TELEGRAM_SEND_TIMEOUT = 90.0
TELEGRAM_RETRY_DELAY_SEC = 2
# Коэффициент "извилистости" ж/д путей для расчета по прямой
RAILWAY_WINDING_FACTOR = 1.25
# =========================
# Настройки кеширования станций OSM
# =========================
# Расписание в формате cron: 15-я минута каждого 2-го часа.
# Установите в "" (пустую строку), чтобы отключить.
STATIONS_CACHE_CRON_SCHEDULE = "0 */8 * * *"