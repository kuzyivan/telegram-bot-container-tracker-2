import os
import logging
import traceback
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
    logger.info(f"📬 [Scheduler] === НАЧАЛО проверки почты: {datetime.now()}")

    if not EMAIL or not PASSWORD:
        logger.error(f"❌ EMAIL или PASSWORD не заданы!")
        return

    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
            messages = list(mailbox.fetch(reverse=True, limit=2))  # Только 2 последних письма!
            logger.info(f"🔎 Найдено {len(messages)} последних писем для проверки.")

            latest_file = None
            latest_date = None
            latest_msg_subject = None

            for msg in messages:
                logger.info(f"Письмо: {msg.date}, тема: {msg.subject}, вложения: {[a.filename for a in msg.attachments]}")
                for att in msg.attachments:
                    logger.info(f"Вложение: {att.filename}")
                    if att.filename and att.filename.lower().endswith('.xlsx'):
                        msg_date = msg.date
                        if latest_date is None or msg_date > latest_date:
                            latest_date = msg_date
                            latest_file = (att, att.filename)
                            latest_msg_subject = msg.subject
                            logger.info(f"Файл выбран для скачивания: {att.filename} из письма '{msg.subject}' ({msg.date})")
            if latest_file:
                safe_filename = latest_file[1].replace(' ', '_')
                filepath = os.path.join(DOWNLOAD_FOLDER, safe_filename)
                with open(filepath, 'wb') as f:
                    f.write(latest_file[0].payload)
                logger.info(
                    f"📥 Скачан файл: {safe_filename} "
                    f"({filepath}), тема письма: \"{latest_msg_subject}\", дата письма: {latest_date} ({datetime.now()})"
                )
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.create_task(process_file(filepath))
            else:
                logger.warning("⚠ Не найден ни один файл .xlsx для скачивания в последних 2 письмах!")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}\n{traceback.format_exc()}")

    logger.info(f"📬 [Scheduler] === КОНЕЦ проверки почты: {datetime.now()}")

async def process_file(filepath):
    try:
        logger.info(f"📝 Начата обработка файла {filepath} ({datetime.now()})")
        df = pd.read_excel(filepath, skiprows=3)
        if 'Номер контейнера' not in df.columns:
            raise ValueError("['Номер контейнера']")

        if 'Дата и время операции' in df.columns:
            df['Дата и время операции'] = pd.to_datetime(
                df['Дата и время операции'].astype(str).str.strip(),
                format='%d.%m.%Y %H:%M',
                errors='coerce'
            )
        logger.info(f"Пустых дат операций: {df['Дата и время операции'].isna().sum()}")

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
                operation_date=row.get('Дата и время операции'),
                waybill=str(row.get('Номер накладной', '')).strip(),
                km_left=km_left,
                forecast_days=forecast_days,
                wagon_number=str(row.get('Номер вагона', '')).strip(),
                operation_road=str(row.get('Дорога операции', '')).strip()
            )
            records.append(record)

        logger.info(f"Будет добавлено в БД строк: {len(records)}. Пример первой: {records[0] if records else 'пусто'}")

        async with SessionLocal() as session:
            await session.execute(delete(Tracking))
            session.add_all(records)
            await session.commit()

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База данных обновлена из файла {os.path.basename(filepath)} ({datetime.now()})")
        logger.info(f"📦 Загружено строк: {len(records)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")
        logger.info(f"📝 Обработка файла завершена: {filepath} ({datetime.now()})")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}\n{traceback.format_exc()}")

def start_mail_checking():
    logger.info(f"📩 Запущена ручная проверка почты: {datetime.now()}")
    check_mail()
    logger.info(f"🔄 Ручная проверка почты завершена: {datetime.now()}")
