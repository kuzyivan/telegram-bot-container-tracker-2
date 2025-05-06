import os
import sqlite3
import logging
from imap_tools import MailBox
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

# Создание таблицы при необходимости
def ensure_database_exists():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_number TEXT,
            from_station TEXT,
            to_station TEXT,
            current_station TEXT,
            operation TEXT,
            operation_date TEXT,
            waybill TEXT,
            km_left INTEGER,
            forecast_days INTEGER
        )
    ''')
    conn.commit()
    conn.close()

# Проверка почты и скачивание Excel-файлов
def check_mail():
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
            logger.info("📬 Вход в почту успешен")

            messages = list(mailbox.fetch(reverse=True, limit=3))
            logger.info(f"📨 Найдено писем: {len(messages)}")

            for msg in messages:
                logger.info(f"✉️ Тема: {msg.subject} | Дата: {msg.date}")

                for att in msg.attachments:
                    logger.info(f"📎 Вложение: {att.filename} | Размер: {len(att.payload)} байт")

                    if att.filename.endswith('.xlsx'):
                        filepath = os.path.join(DOWNLOAD_FOLDER, att.filename)
                        with open(filepath, 'wb') as f:
                            f.write(att.payload)
                        logger.info(f"📥 Скачан файл: {filepath}")
                        process_file(filepath)

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")


# Обработка Excel-файла
def process_file(filepath):
    try:
        df = pd.read_excel(filepath, skiprows=3)  # с 4-й строки
        logger.info(f"📊 Прочитано строк: {len(df)}")
        logger.info(f"📑 Колонки в файле: {list(df.columns)}")

        if 'Номер контейнера' not in df.columns:
            logger.warning(f"⚠️ В файле {os.path.basename(filepath)} нет колонки 'Номер контейнера'. Пропуск.")
            return

        if df.empty:
            logger.warning(f"⚠️ Файл {os.path.basename(filepath)} пустой. Пропуск.")
            return

        records = []
        for _, row in df.iterrows():
            km_left = int(row.get('Расстояние оставшееся', 0)) if pd.notna(row.get('Расстояние оставшееся')) else 0
            forecast_days = (km_left + 599) // 600 if km_left > 0 else 0
            records.append((
                str(row['Номер контейнера']).strip().upper(),
                str(row.get('Станция отправления', '')).strip(),
                str(row.get('Станция назначения', '')).strip(),
                str(row.get('Станция операции', '')).strip(),
                str(row.get('Операция', '')).strip(),
                str(row.get('Дата и время операции', '')).strip(),
                str(row.get('Номер накладной', '')).strip(),
                km_left,
                forecast_days
            ))

        if not records:
            logger.warning(f"⚠️ Нет валидных строк в {os.path.basename(filepath)}.")
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracking")
        cursor.executemany("""
            INSERT INTO tracking (
                container_number, from_station, to_station,
                current_station, operation, operation_date,
                waybill, km_left, forecast_days
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
        conn.close()
        logger.info(f"✅ База данных обновлена из файла {os.path.basename(filepath)}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")

# Плановая проверка почты
from apscheduler.triggers.interval import IntervalTrigger

def schedule_mail_checking(scheduler):
    scheduler.add_job(start_mail_checking, IntervalTrigger(minutes=30))
    logger.info("🕒 Задача проверки почты зарегистрирована (каждые 30 мин).")

# Ручной запуск
def start_mail_checking():
    logger.info("📩 Запущена проверка почты...")
    ensure_database_exists()
    check_mail()
    logger.info("🔄 Проверка почты завершена.")
