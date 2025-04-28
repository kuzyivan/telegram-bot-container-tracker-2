import os
import time
import sqlite3
import pandas as pd
from imap_tools import MailBox, AND
from apscheduler.schedulers.background import BackgroundScheduler

# Настройки из переменных окружения
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'
DAYS_TO_KEEP = 5  # дней хранить скачанные файлы

# Создаём папку для загрузки, если её нет
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
    print("✅ База данных инициализирована.")

# Удаление старых файлов из папки загрузки
def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(file_path):
            age_days = (now - os.path.getctime(file_path)) / (60 * 60 * 24)
            if age_days > DAYS_TO_KEEP:
                os.remove(file_path)
                print(f"🗑 Удалён старый файл: {filename}")

# Проверка почты и загрузка новых файлов
def check_mail():
    print("\n📩 Проверка почты...")
    cleanup_old_files()
    print(f"DEBUG: EMAIL={EMAIL!r}, PASSWORD_SET={bool(PASSWORD)}")
    try:
        with MailBox('imap.yandex.ru').login(EMAIL, PASSWORD) as mailbox:
            print("DEBUG: Вход в почту успешен")
            for msg in mailbox.fetch(AND(seen=False)):
                for att in msg.attachments:
                    fname = att.filename or ''
                    print(f"DEBUG: Найдено вложение: {fname!r}")
                    if fname.lower().endswith('.xlsx'):
                        fp = os.path.join(DOWNLOAD_FOLDER, fname)
                        with open(fp, 'wb') as f:
                            f.write(att.payload)
                        print(f"📥 Скачан файл: {fp}")
                        process_excel(fp)
                mailbox.flag(msg.uid, MailBox.flags.SEEN, True)
    except Exception as e:
        print(f"❌ Ошибка при проверке почты: {e}")

# Обработка Excel и запись в базу
def process_excel(filepath):
    print(f"\n🔍 Обработка Excel файла: {filepath}")
    try:
        df = pd.read_excel(filepath, header=3)  # Читаем с 4-й строки!
        print(f"DEBUG: Загружено строк: {len(df)}")
        print(f"DEBUG: Названия колонок: {list(df.columns)}")
        df.columns = [(str(c) or '').strip().replace('\ufeff', '') for c in df.columns]

        if 'Номер контейнера' not in df.columns:
            print("❗ В файле нет нужной колонки 'Номер контейнера'.")
            return

        df = df.dropna(subset=['Номер контейнера'])
        df = df.rename(columns={
            'Номер контейнера': 'container_number',
            'Станция отправления': 'departure_station',
            'Станция назначения': 'arrival_station',
            'Станция операции': 'operation_station',
            'Операция': 'operation_type',
            'Дата и время операции': 'operation_datetime',
            'Номер накладной': 'waybill_number',
            'Расстояние оставшееся': 'distance_left'
        })
        df['operation_datetime'] = df['operation_datetime'].astype(str)
        
        conn = sqlite3.connect(DB_FILE)
        df.to_sql('tracking', conn, if_exists='append', index=False)
        conn.close()
        print(f"✅ Успешно добавлено записей в БД: {len(df)}")
    except Exception as e:
        print(f"❌ Ошибка обработки файла {filepath}: {e}")

# Запуск фоновой проверки почты
def start_mail_checking():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=40)
    scheduler.start()
    check_mail()
    print("🔄 Фоновая проверка почты запущена.")
