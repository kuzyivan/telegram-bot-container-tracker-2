import os
import logging
from imap_tools import MailBox
import pandas as pd
import sqlalchemy as sa
from db import engine, SessionLocal
from models import Tracking, TrackingTemp, create_temp_table

logger = logging.getLogger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

async def check_mail():
    logger.info("📬 [Scheduler] Запущена проверка почты по расписанию...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, fetch_latest_excel)
        
        if filepath:
            logger.info(f"📥 Скачан самый свежий файл: {filepath}")
            await process_file(filepath)
        else:
            logger.info("⚠ Нет подходящих Excel-вложений в почте.")
    except Exception as e:
        logger.error(f"❌ Ошибка во время проверки почты: {e}", exc_info=True)

def fetch_latest_excel():
    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
        messages = list(mailbox.fetch(reverse=True, limit=10))
        for msg in messages:
            for att in msg.attachments:
                if att.filename.lower().endswith('.xlsx'):
                    filepath = os.path.join(DOWNLOAD_FOLDER, att.filename)
                    with open(filepath, 'wb') as f:
                        f.write(att.payload)
                    return filepath
    return None

async def process_file(filepath):
    try:
        df = pd.read_excel(filepath, skiprows=3)
        if 'Номер контейнера' not in df.columns:
            raise ValueError("В Excel-файле отсутствует столбец 'Номер контейнера'")

        records_to_load = []
        for _, row in df.iterrows():
            try:
                km_left = int(row.get('Расстояние оставшееся', 0))
                record = {
                    'container_number': str(row['Номер контейнера']).strip().upper(),
                    'from_station': str(row.get('Станция отправления', '')).strip(),
                    'to_station': str(row.get('Станция назначения', '')).strip(),
                    'current_station': str(row.get('Станция операции', '')).strip(),
                    'operation': str(row.get('Операция', '')).strip(),
                    'operation_date': str(row.get('Дата и время операции', '')).strip(),
                    'waybill': str(row.get('Номер накладной', '')).strip(),
                    'km_left': km_left,
                    'forecast_days': round(km_left / 600, 1) if km_left else 0.0,
                    'wagon_number': str(row.get('Номер вагона', '')).strip(),
                    'operation_road': str(row.get('Дорога операции', '')).strip()
                }
                records_to_load.append(record)
            except (ValueError, TypeError) as e:
                logger.warning(f"Пропущена строка из-за ошибки данных: {row}. Ошибка: {e}")
                continue
        
        # --- АТОМАРНОЕ ОБНОВЛЕНИЕ ---
        await create_temp_table()

        # Шаг 1: Очистка и загрузка данных во временную таблицу через сессию
        async with SessionLocal() as session:
            async with session.begin():
                # Полностью очищаем временную таблицу перед новой загрузкой
                await session.execute(sa.delete(TrackingTemp))
                if records_to_load:
                    # Используем bulk_insert_mappings внутри run_sync, т.к. это синхронный метод
                    await session.run_sync(
                         lambda s: s.bulk_insert_mappings(TrackingTemp, records_to_load)
                    )
        
        # Шаг 2: Атомарная замена таблиц через низкоуровневые DDL-команды
        async with engine.begin() as conn:
            await conn.execute(sa.text("LOCK TABLE tracking IN ACCESS EXCLUSIVE MODE"))
            await conn.execute(sa.text("DROP TABLE IF EXISTS tracking_old CASCADE"))
            await conn.execute(sa.text("ALTER TABLE tracking RENAME TO tracking_old"))
            await conn.execute(sa.text("ALTER TABLE tracking_temp RENAME TO tracking"))

        last_date = df['Дата и время операции'].dropna().max()
        logger.info(f"✅ База данных атомарно обновлена из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records_to_load)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при обработке файла {filepath}: {e}", exc_info=True)

async def start_mail_checking():
    logger.info("📩 Запущена первоначальная проверка почты...")
    await check_mail()
    logger.info("🔄 Первоначальная проверка почты завершена.")
