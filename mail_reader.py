import os
import logging
import asyncio
from datetime import datetime
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
# ИСПРАВЛЕНО: Добавлен импорт MailBox из библиотеки imap_tools
from imap_tools import MailBox 

from db import SessionLocal
from models import Tracking

logger = logging.getLogger(__name__)

EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.yandex.ru')
DOWNLOAD_FOLDER = 'downloads'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def _blocking_fetch_latest_excel():
    """Синхронная (блокирующая) функция для скачивания файла с почты."""
    latest_file_path = None
    latest_date = None
    try:
        with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder='INBOX') as mailbox:
            for msg in mailbox.fetch():
                for att in msg.attachments:
                    if att.filename.lower().endswith(('.xlsx', '.xls')):
                        msg_date = msg.date
                        if latest_date is None or msg_date > latest_date:
                            latest_date = msg_date
                            # Сохраняем аттачмент во временный файл
                            filepath = os.path.join(DOWNLOAD_FOLDER, att.filename)
                            with open(filepath, 'wb') as f:
                                f.write(att.payload)
                            latest_file_path = filepath
    except Exception as e:
        logger.error(f"Ошибка при доступе к почтовому ящику: {e}")
        return None
    return latest_file_path

def _blocking_process_file(filepath: str):
    """
    Синхронная (блокирующая) функция для обработки Excel-файла.
    Читает файл, преобразует данные и возвращает список словарей.
    """
    try:
        df = pd.read_excel(filepath, skiprows=3)
        
        # Переименование колонок для удобства
        df.rename(columns={
            'Номер контейнера': 'container_number',
            'Станция отправления': 'from_station',
            'Станция назначения': 'to_station',
            'Станция операции': 'current_station',
            'Операция': 'operation',
            'Дата и время операции': 'operation_date',
            'Номер накладной': 'waybill',
            'Расстояние оставшееся': 'km_left',
            'Номер вагона': 'wagon_number',
            'Дорога операции': 'operation_road',
        }, inplace=True)
        
        if 'container_number' not in df.columns:
            raise ValueError("В файле отсутствует обязательная колонка 'Номер контейнера'")

        # Преобразование данных
        df['container_number'] = df['container_number'].astype(str).str.strip().str.upper()
        df['operation_date'] = pd.to_datetime(df['operation_date'], errors='coerce')
        df.dropna(subset=['container_number', 'operation_date'], inplace=True) # Удаляем строки без номера или даты

        df['km_left'] = pd.to_numeric(df['km_left'], errors='coerce').fillna(0).astype(int)
        df['forecast_days'] = df.apply(lambda row: round(row['km_left'] / 600, 1) if row['km_left'] > 0 else 0.0, axis=1)

        # Заполняем пустые значения
        for col in ['from_station', 'to_station', 'current_station', 'operation', 'waybill', 'wagon_number', 'operation_road']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().fillna('')
        
        # Возвращаем список словарей, готовых для вставки в БД
        return df.to_dict('records')

    except Exception as e:
        logger.error(f"Ошибка при обработке файла {filepath}: {e}")
        return []

async def check_mail():
    """Основная асинхронная задача для проверки почты и обновления БД."""
    logger.info("📬 [Scheduler] Запущена проверка почты...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    loop = asyncio.get_running_loop()
    
    # 1. Скачиваем файл (блокирующая операция)
    filepath = await loop.run_in_executor(None, _blocking_fetch_latest_excel)
    if not filepath:
        logger.info("📪 Новых файлов в почте не найдено.")
        return
    logger.info(f"📥 Скачан самый свежий файл: {os.path.basename(filepath)}")

    # 2. Обрабатываем файл (блокирующая операция)
    records_to_upsert = await loop.run_in_executor(None, _blocking_process_file, filepath)
    if not records_to_upsert:
        logger.warning(f"Не удалось извлечь данные из файла {os.path.basename(filepath)}.")
        return

    # 3. Обновляем БД (асинхронная операция)
    async with SessionLocal() as session:
        # Используем On Conflict (UPSERT) для атомарного обновления данных
        stmt = insert(Tracking).values(records_to_upsert)
        update_dict = {c.name: c for c in stmt.excluded if c.name not in ["id", "container_number"]}
        
        stmt = stmt.on_conflict_do_update(
            index_elements=['container_number'],
            set_=update_dict
        )
        await session.execute(stmt)
        await session.commit()
    
    logger.info(f"✅ База данных обновлена. Обработано {len(records_to_upsert)} записей.")
    try:
        os.remove(filepath) # Удаляем временный файл
    except OSError as e:
        logger.error(f"Не удалось удалить временный файл {filepath}: {e}")

async def start_mail_checking():
    logger.info("📩 Запущена первоначальная проверка почты при старте бота...")
    await check_mail()
    logger.info("🔄 Первоначальная проверка почты завершена.")

