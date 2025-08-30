from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) # type: ignore
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get("PORT", 10000))
#стабильная версия
# =========================
# Настройки уведомлений
# =========================
# Колонки для Excel-отчета по дислокации
TRACKING_REPORT_COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

# Настройки отправки в Telegram
TELEGRAM_SEND_ATTEMPTS = 3      # Количество попыток отправки
TELEGRAM_SEND_TIMEOUT = 90.0    # Таймаут на чтение/запись в секундах
TELEGRAM_RETRY_DELAY_SEC = 2    # Начальная задержка перед повторной отправкой (будет увеличиваться экспоненциально)
