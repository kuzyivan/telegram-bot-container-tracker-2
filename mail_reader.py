import os
import logging
from imap_tools import MailBox
from datetime import datetime
import pandas as pd
from sqlalchemy import delete
from db import SessionLocal
from models import Tracking
import asyncio

logger = logging.getLogger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def check_mail():
    logger.info("📬 [Scheduler] Запущена проверка почты по расписанию (каждые 15 минут)...")

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
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.create_task(process_file(filepath))
            else:
                logger.info("⚠ Нет подходящих Excel-вложений в почте, обновление базы не требуется.")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")

async def process_file(filepath):
    try:
        df = pd.read_excel(filepath, skiprows=3)
        if 'Номер контейнера' not in df.columns:
            raise ValueError("['Номер контейнера']")

        records = []
        for _, row in df.iterrows():
            km_left = int(row.get('Расстояние оставшееся', 0))
            forecast_days = round(km_left / 600, 1) if km_left else 0.0

            record = Tracking(
                container_number=str(row['Номер контейнера']).strip().upper(),
                from_station=str(row.get('Станция отправления', '')).strip(),
                to_station=str(row.get('Станция назначения', '')).strip(),
                current_station=str(row.get('Станция операции', '')).strip(),
                operation=str(row.get('Операция', '')).strip(),
                operation_date=str(row.get('Дата и время операции', '')).strip(),
                waybill=str(row.get('Номер накладной', '')).strip(),
                km_left=km_left,
                forecast_days=forecast_days,
                wagon_number=str(row.get('Номер вагона', '')).strip(),
                operation_road=str(row.get('Дорога операции', '')).strip()
            )
            records.append(record)

        async with SessionLocal() as session:
            await session.execute(delete(Tracking))
            session.add_all(records)
            await session.commit()

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База данных обновлена из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")

def start_mail_checking():
    logger.info("📩 Запущена проверка почты (ручной запуск)...")
    check_mail()
    logger.info("🔄 Проверка почты завершена.")
