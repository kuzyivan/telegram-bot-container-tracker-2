# Новая структура для интеграции в существующий bot.py

# mail_reader.py
import os
import time
import sqlite3
import pandas as pd
from imap_tools import MailBox, AND
from apscheduler.schedulers.background import BackgroundScheduler

# Настройки
EMAIL = 'bottrack@yandex.ru'
PASSWORD = 'ТВОЙ_ПАРОЛЬ_ОТ_ПОЧТЫ'
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'
DAYS_TO_KEEP = 5

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_number TEXT,
        departure_station TEXT,
        arrival_station TEXT,
        operation_station TEXT,
        operation_type TEXT,
        operation_datetime TEXT,
        waybill_number TEXT,
        distance_left INTEGER
    )
    ''')
    conn.commit()
    conn.close()

# Очистка старых файлов
def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(file_path):
            file_age_days = (now - os.path.getctime(file_path)) / (60 * 60 * 24)
            if file_age_days > DAYS_TO_KEEP:
                os.remove(file_path)
                print(f"Удалён старый файл: {filename}")

# Загрузка и обработка новых писем
def check_mail():
    print("Проверка почты...")
    cleanup_old_files()
    with MailBox('imap.yandex.ru').login(EMAIL, PASSWORD) as mailbox:
        for msg in mailbox.fetch(AND(seen=False, subject=lambda x: x and x.startswith('Отчёт слежения TrackerTG №'))):
            for att in msg.attachments:
                if att.filename.startswith('103') and att.filename.endswith('.xlsx'):
                    filepath = os.path.join(DOWNLOAD_FOLDER, att.filename)
                    with open(filepath, 'wb') as f:
                        f.write(att.payload)
                    print(f"Скачан файл: {filepath}")
                    process_excel(filepath)
            mailbox.flag(msg.uid, MailBox.flags.SEEN, True)

# Обработка Excel файла и запись в базу данных
def process_excel(filepath):
    df = pd.read_excel(filepath, skiprows=3)
    df.columns = [
        'container_number',
        'departure_station',
        'arrival_station',
        'operation_station',
        'operation_type',
        'operation_datetime',
        'waybill_number',
        'distance_left'
    ]
    df = df.dropna(subset=['container_number'])
    conn = sqlite3.connect(DB_FILE)
    df.to_sql('tracking', conn, if_exists='append', index=False)
    conn.close()
    print(f"Обработано записей: {len(df)}")

# Функция запуска планировщика для использования в bot.py
def start_mail_checking():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=40)
    scheduler.start()
    print('Фоновая проверка почты запущена.')
