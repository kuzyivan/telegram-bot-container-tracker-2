import os
import sqlite3
import logging
from imap_tools import MailBox, AND
from datetime import datetime
import pandas as pd

# Логирование
logger = logging.getLogger(__name__)

# Константы
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'

# Убедимся, что папка для скачивания существует
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Проверка базы данных
def ensure_database_exists():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tracking (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_number TEXT,
                        from_station TEXT,
                        to_station TEXT,
                        current_station TEXT,
                        operation TEXT,
                        operation_date TEXT,
                        waybill TEXT,
                        km_left INTEGER,
                        forecast_days REAL,
                        wagon_number TEXT,
                        operation_road TEXT)''')
    conn.commit()
    conn.close()

# Проверка почты и скачивание самого нового Excel-файла
def check_mail():
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
            latest_file = None
            latest_date = None

            for msg in mailbox.fetch():
                for att in msg.attachments:
                    if att.filename.endswith('.xlsx'):
                        msg_date = msg.date
                        if latest_date is None or msg_date > latest_date:
                            latest_date = msg_date
                            latest_file = (att, att.filename)

            if latest_file:
                filepath = os.path.join(DOWNLOAD_FOLDER, latest_file[1])
                with open(filepath, 'wb') as f:
                    f.write(latest_file[0].payload)
                logger.info(f"📥 Скачан самый свежий файл: {filepath}")
                process_file(filepath)
            else:
                logger.warning("⚠ Нет подходящих Excel-вложений в почте.")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")

# Обработка Excel-файла
def process_file(filepath):
    try:
        df = pd.read_excel(filepath, skiprows=3)  # Начинаем с 4 строки
        if 'Номер контейнера' not in df.columns:
            raise ValueError("['Номер контейнера']")

        records = []
        for _, row in df.iterrows():
            km_left = int(row.get('Расстояние оставшееся', 0))
            forecast_days = round(km_left / 600, 1) if km_left else 0.0
            wagon_number = str(row.get('Номер вагона', '')).strip()
            operation_road = str(row.get('Дорога операции', '')).strip()

            records.append(
                (
                    str(row['Номер контейнера']).strip().upper(),
                    str(row.get('Станция отправления', '')).strip(),
                    str(row.get('Станция назначения', '')).strip(),
                    str(row.get('Станция операции', '')).strip(),
                    str(row.get('Операция', '')).strip(),
                    str(row.get('Дата и время операции', '')).strip(),
                    str(row.get('Номер накладной', '')).strip(),
                    km_left,
                    forecast_days,
                    wagon_number,
                    operation_road
                )
            )

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracking")
        cursor.executemany("""
            INSERT INTO tracking (container_number, from_station, to_station, current_station,
                                  operation, operation_date, waybill, km_left, forecast_days,
                                  wagon_number, operation_road)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", records)
        conn.commit()
        conn.close()

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База данных обновлена из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")

# Стартовый метод
def start_mail_checking():
    logger.info("📩 Запущена проверка почты...")
    ensure_database_exists()
    check_mail()
    logger.info("🔄 Проверка почты завершена.")
