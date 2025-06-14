import os
from imap_tools.mailbox import MailBox
import pandas as pd
from sqlalchemy import delete
from db import SessionLocal
from models import Tracking
from logger import get_logger

logger = get_logger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

async def check_mail():
    logger.info("📬 [Scheduler] Запущена проверка почты по расписанию (каждые 15 минут)...")

    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
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
            logger.info("⚠ Нет подходящих Excel-вложений в почте, обновление базы не требуется.")

    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}", exc_info=True)

def fetch_latest_excel():
    latest_file = None
    latest_date = None
    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox: # type: ignore
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
                return filepath
    except Exception as e:
        logger.error(f"❌ Ошибка при работе с почтой: {e}", exc_info=True)
    return None

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

        # Атомарно обновляем данные в базе через временную таблицу:
        with SessionLocal() as session:
            try:
                # Создаём временную таблицу
                session.execute('CREATE TEMP TABLE IF NOT EXISTS tracking_tmp (LIKE tracking INCLUDING ALL)')
                session.execute('TRUNCATE tracking_tmp')
                session.bulk_save_objects(records)
                session.commit()

                # Меняем данные в основной таблице атомарно
                session.execute('TRUNCATE tracking')
                session.execute('INSERT INTO tracking SELECT * FROM tracking_tmp')
                session.execute('DROP TABLE tracking_tmp')
                session.commit()
                logger.info("✅ База данных обновлена атомарно через временную таблицу.")
            except Exception as db_e:
                session.rollback()
                logger.error(f"❌ Ошибка при обновлении базы: {db_e}", exc_info=True)
                raise

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База данных обновлена из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}", exc_info=True)

async def start_mail_checking():
    logger.info("📩 Запущена проверка почты (ручной запуск)...")
    await check_mail()
    logger.info("🔄 Проверка почты завершена.")
