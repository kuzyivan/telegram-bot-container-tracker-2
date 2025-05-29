import os
import logging
import asyncio
from imap_tools import aioimaplib
from datetime import datetime
import pandas as pd
from sqlalchemy import delete
from db import SessionLocal
from models import Tracking

logger = logging.getLogger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

async def check_mail():
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        # асинхронный клиент для imap-tools (aioimaplib)
        client = aioimaplib.AioImapClient(IMAP_SERVER, 993, ssl=True)
        await client.wait_hello_from_server()
        await client.login(EMAIL, PASSWORD)
        await client.select('INBOX')
        _, data = await client.uid('search', None, 'ALL')
        uids = data[0].decode().split()
        latest_file = None
        latest_date = None

        for uid in uids[::-1]:  # С конца к началу (новые письма)
            _, msg_data = await client.uid('fetch', uid, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    import email
                    msg = email.message_from_bytes(response_part[1])
                    msg_date = email.utils.parsedate_to_datetime(msg['Date'])
                    for part in msg.walk():
                        if part.get_content_maintype() == 'application' and part.get_filename() and part.get_filename().endswith('.xlsx'):
                            if latest_date is None or msg_date > latest_date:
                                latest_date = msg_date
                                latest_file = (part, part.get_filename())
            if latest_file:
                break

        if latest_file:
            filepath = os.path.join(DOWNLOAD_FOLDER, latest_file[1])
            with open(filepath, 'wb') as f:
                f.write(latest_file[0].get_payload(decode=True))
            logger.info(f"📥 Скачан самый свежий файл: {filepath}")
            await process_file(filepath)
        else:
            logger.warning("⚠ Нет подходящих Excel-вложений в почте.")

        await client.logout()

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")

async def process_file(filepath):
    try:
        df = pd.read_excel(filepath, skiprows=3)
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

async def start_mail_checking():
    logger.info("📩 Запущена проверка почты...")
    await check_mail()
    logger.info("🔄 Проверка почты завершена.")

