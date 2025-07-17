import os
import time
import logging
import pandas as pd
from datetime import datetime
from dateutil import parser
from sqlalchemy import text
from imap_tools import MailBox
from db import SessionLocal
from models import Tracking
from logger import get_logger

logger = get_logger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# === Очистка старых файлов в папке ===
def clean_old_files(folder, days=5):
    now = time.time()
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            if now - os.path.getmtime(filepath) > days * 86400:
                os.remove(filepath)
                logger.info(f"🗑 Удалён старый файл: {filename}")

async def check_mail():
    logger.info("📬 [Scheduler] Запущена проверка почты по расписанию...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в .env.")
        return

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, fetch_latest_excel)
        if result:
            filepath = result
            logger.info(f"📥 Скачан самый свежий файл: {filepath}")
            await process_file(filepath)
        else:
            logger.info("⚠ Нет новых Excel-вложений — обновление не требуется.")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}", exc_info=True)

def fetch_latest_excel():
    latest_file = None
    latest_date = None
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
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
            clean_old_files(DOWNLOAD_FOLDER)
            return filepath
    return None

async def process_file(filepath):
    import traceback
    try:
        df = pd.read_excel(filepath, skiprows=3)

        required_columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Номер вагона', 'Дорога операции'
        ]
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            raise ValueError(f"Отсутствуют столбцы: {', '.join(missing)}")

        records = []
        for _, row in df.iterrows():
            km_left = int(row.get('Расстояние оставшееся', 0)) or 0
            forecast_days = round(km_left / 600, 1) if km_left else 0.0

            operation_date_raw = row.get('Дата и время операции', '')
            operation_date = parser.parse(str(operation_date_raw)) if operation_date_raw else None

            record = Tracking(
                container_number=str(row['Номер контейнера']).strip().upper(),
                from_station=str(row.get('Станция отправления', '')).strip(),
                to_station=str(row.get('Станция назначения', '')).strip(),
                current_station=str(row.get('Станция операции', '')).strip(),
                operation=str(row.get('Операция', '')).strip(),
                operation_date=operation_date,
                waybill=str(row.get('Номер накладной', '')).strip(),
                km_left=km_left,
                forecast_days=forecast_days,
                wagon_number=str(row.get('Номер вагона', '')).strip(),
                operation_road=str(row.get('Дорога операции', '')).strip()
            )
            records.append(record)

        async with SessionLocal() as session:
            await session.execute(text('CREATE TEMP TABLE IF NOT EXISTS tracking_tmp (LIKE tracking INCLUDING ALL)'))
            await session.execute(text('TRUNCATE tracking_tmp'))

            for record in records:
                await session.execute(
                    text("""
                        INSERT INTO tracking_tmp (
                            container_number, from_station, to_station, current_station, operation,
                            operation_date, waybill, km_left, forecast_days, wagon_number, operation_road
                        ) VALUES (
                            :container_number, :from_station, :to_station, :current_station, :operation,
                            :operation_date, :waybill, :km_left, :forecast_days, :wagon_number, :operation_road
                        )
                    """),
                    {
                        'container_number': record.container_number,
                        'from_station': record.from_station,
                        'to_station': record.to_station,
                        'current_station': record.current_station,
                        'operation': record.operation,
                        'operation_date': record.operation_date,
                        'waybill': record.waybill,
                        'km_left': record.km_left,
                        'forecast_days': record.forecast_days,
                        'wagon_number': record.wagon_number,
                        'operation_road': record.operation_road,
                    }
                )

            await session.commit()
            await session.execute(text('TRUNCATE tracking'))
            await session.execute(text('INSERT INTO tracking SELECT * FROM tracking_tmp'))
            await session.execute(text('DROP TABLE IF EXISTS tracking_tmp'))
            await session.commit()

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База обновлена из: {os.path.basename(filepath)}")
        logger.info(f"📦 Строк загружено: {len(records)}")
        logger.info(f"🕓 Последняя дата операции: {last_date}")
        logger.info(f"🚉 Станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")
        logger.error(traceback.format_exc())

async def start_mail_checking():
    logger.info("📩 Ручной запуск проверки почты...")
    await check_mail()
    logger.info("🔁 Проверка завершена.")