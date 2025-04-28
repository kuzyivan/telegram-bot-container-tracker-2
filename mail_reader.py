import os
import time
import sqlite3
import pandas as pd
from imap_tools import MailBox, AND
from apscheduler.schedulers.background import BackgroundScheduler

# mail_reader.py
# Чтение почты, загрузка Excel-файлов и запись данных в SQLite

# Настройки из переменных окружения
EMAIL = os.getenv('EMAIL')         # bottrack@yandex.ru
PASSWORD = os.getenv('PASSWORD')   # пароль от почты
DOWNLOAD_FOLDER = 'downloads'
DB_FILE = 'tracking.db'
DAYS_TO_KEEP = 5                   # дней хранить скачанные файлы

# Создаём папку для загрузки, если её нет
ios.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

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

# Удаление старых файлов из папки задароженных

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
    print("📩 Проверка почты...")
    cleanup_old_files()
    # DEBUG: выводим параметры логина
    print(f"DEBUG: EMAIL={EMAIL!r}, PASSWORD_SET={bool(PASSWORD)}")
    try:
        with MailBox('imap.yandex.ru').login(EMAIL, PASSWORD) as mailbox:
            print("DEBUG: Вход в почту успешен")
            # Фильтруем непрочитанные письма по теме
            msgs = list(mailbox.fetch(
                AND(
                    seen=False,
                    subject=lambda x: isinstance(x, str) and x.startswith('Отчёт слежения TrackerTG №')
                )
            ))
            print(f"DEBUG: Найдено писем: {len(msgs)}")
            for msg in msgs:
                print(f"DEBUG: Обрабатываем письмо: {{msg.subject!r}}")
                # Смотрим имена всех вложений
                filenames = [att.filename for att in msg.attachments]
                print(f"DEBUG: Вложений: {filenames}")
                # Скачиваем подходящие файлы
                for att in msg.attachments:
                    if att.filename and att.filename.startswith('103') and att.filename.endswith('.xlsx'):
                        fp = os.path.join(DOWNLOAD_FOLDER, att.filename)
                        with open(fp, 'wb') as f:
                            f.write(att.payload)
                        print(f"📥 Скачан файл: {fp}")
                        process_excel(fp)
                # Отмечаем письмо как прочитанное
                mailbox.flag(msg.uid, MailBox.flags.SEEN, True)
    except Exception as e:
        print(f"❌ Ошибка при проверке почты: {e}")

# Обработка Excel и запись в базу

def process_excel(filepath):
    try:
        # Заголовки находятся на третьей строке (header=2)
        df = pd.read_excel(filepath, header=2)
        # Нормализуем имена колонок: убираем BOM и пробелы
        df.columns = [(str(c) or '').strip().replace('\ufeff', '') for c in df.columns]
        # Оставляем только строки с номером контейнера
        df = df.dropna(subset=['Номер контейнера'])
        # Переименовываем столбцы под структуру БД
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
        # Приводим дату-время к строкам для SQLite
        df['operation_datetime'] = df['operation_datetime'].astype(str)
        # Записываем в таблицу tracking
        conn = sqlite3.connect(DB_FILE)
        df.to_sql('tracking', conn, if_exists='append', index=False)
        conn.close()
        print(f"✅ Обработано {len(df)} записей из {os.path.basename(filepath)}")
    except Exception as e:
        print(f"❌ Ошибка обработки {filepath}: {e}")

# Запуск фоновой проверки почты

def start_mail_checking():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=40)
    scheduler.start()
    # Вызываем проверку сразу после старта
    check_mail()
    print("🔄 Фоновая проверка почты запущена.")
