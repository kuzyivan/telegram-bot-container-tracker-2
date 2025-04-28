import os
import sqlite3
import logging
import pandas as pd
from imap_tools import MailBox

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAP_SERVER = 'imap.yandex.ru'
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('EMAIL_PASSWORD')
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'

# Инициализация папки для загрузок
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Создание базы данных при необходимости
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_number TEXT,
            from_station TEXT,
            to_station TEXT,
            operation_station TEXT,
            operation TEXT,
            operation_date TEXT,
            waybill TEXT,
            km_remains INTEGER
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована.")

# Загрузка Excel файла в базу данных
def load_excel_to_db(file_path):
    try:
        df = pd.read_excel(file_path, skiprows=3)
        df = df.rename(columns=lambda x: x.strip())
        if 'Номер контейнера' not in df.columns:
            raise ValueError(['Номер контейнера'])

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tracking')

        for _, row in df.iterrows():
            cursor.execute('''
                INSERT INTO tracking (
                    container_number, from_station, to_station, 
                    operation_station, operation, operation_date, 
                    waybill, km_remains
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row.get('Номер контейнера', ''),
                row.get('Отправление', ''),
                row.get('Назначение', ''),
                row.get('Станция операции', ''),
                row.get('Операция', ''),
                row.get('Дата операции', ''),
                row.get('Накладная', ''),
                row.get('Остаток пути, км', 0)
            ))

        conn.commit()
        conn.close()
        logger.info(f"✅ Данные успешно загружены из {file_path}")
    except Exception as e:
        logger.error(f"❌ Ошибка обработки {file_path}: {e}")

# Проверка и загрузка новых писем
def check_mail():
    logger.info("📩 Проверка почты...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ Не заданы EMAIL или EMAIL_PASSWORD в переменных окружения!")
        return

    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD) as mailbox:
            logger.debug(f"DEBUG: EMAIL='{EMAIL}', PASSWORD_SET={bool(PASSWORD)}")
            logger.debug("DEBUG: Вход в почту успешен")

            for msg in mailbox.fetch():
                for att in msg.attachments:
                    logger.debug(f"DEBUG: Вложение: '{att.filename}'")
                    if att.filename.lower().endswith('.xlsx'):
                        file_path = os.path.join(DOWNLOAD_FOLDER, att.filename)
                        with open(file_path, 'wb') as f:
                            f.write(att.payload)
                        logger.info(f"📥 Скачан файл: {file_path}")
                        load_excel_to_db(file_path)
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")

# Автоматический запуск проверки почты
def start_mail_checking():
    from apscheduler.schedulers.background import BackgroundScheduler

    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=5)
    scheduler.start()
    logger.info("🔄 Фоновая проверка почты запущена.")
