import os
import time
import sqlite3
import pandas as pd
from imap_tools import MailBox, AND
from apscheduler.schedulers.background import BackgroundScheduler

# Настройки из окружения
EMAIL = os.getenv('EMAIL')  # bottrack@yandex.ru
PASSWORD = os.getenv('PASSWORD')
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'
DAYS_TO_KEEP = 5

# Создаём папку для загрузки
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

# Очистка старых файлов
def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(file_path):
            age = (now - os.path.getctime(file_path)) / (60*60*24)
            if age > DAYS_TO_KEEP:
                os.remove(file_path)
                print(f"🗑 Удалён старый файл: {filename}")

# Загрузка и обработка писем
def check_mail():
    print("📩 Проверка почты...")
    cleanup_old_files()
    # Debug: выводим настройки почты
    print(f"DEBUG: EMAIL={EMAIL!r}, PASSWORD_SET={bool(PASSWORD)}")
    try:
        with MailBox('imap.yandex.ru').login(EMAIL, PASSWORD) as mailbox:
            print("DEBUG: Успешный вход в почтовый ящик")
            # Получаем список непрочитанных писем
            msgs = list(mailbox.fetch(AND(seen=False, subject=lambda x: isinstance(x, str) and x.startswith('Отчёт слежения TrackerTG №'))))
            print(f"DEBUG: Найдено писем: {len(msgs)}")
            for msg in msgs:
                print(f"DEBUG: Обрабатываем письмо с темой: {msg.subject!r}")
                filenames = [att.filename for att in msg.attachments]
                print(f"DEBUG: Вложений: {filenames}")
                for att in msg.attachments:
                    if att.filename and att.filename.startswith('103') and att.filename.endswith('.xlsx'):
                        fp = os.path.join(DOWNLOAD_FOLDER, att.filename)
                        with open(fp, 'wb') as f:
                            f.write(att.payload)
                        print(f"📥 Скачан файл: {fp}")
                        process_excel(fp)
                mailbox.flag(msg.uid, MailBox.flags.SEEN, True)
    except Exception as e:
        print(f"❌ Ошибка при проверке почты: {e}")

# Обработка Excel
def process_excel(filepath):
    try:
        df = pd.read_excel(filepath, header=2)
        df.columns = [(str(c) or '').strip().replace('\ufeff', '') for c in df.columns]
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
        print(f"✅ Обработано {len(df)} записей из {os.path.basename(filepath)}")
    except Exception as e:
        print(f"❌ Ошибка обработки {filepath}: {e}")

# Планировщик
def start_mail_checking():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=40)
    scheduler.start()
    # Запускаем проверку сразу после старта
    check_mail()
    print("🔄 Фоновая проверка почты запущена.")
