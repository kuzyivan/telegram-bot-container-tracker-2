# services/dislocation_importer.py
import os
import pandas as pd
from sqlalchemy import text
import asyncio

from db import SessionLocal
from logger import get_logger
from models import Tracking
from services.imap_service import ImapService
from services.train_event_notifier import process_dislocation_for_train_events # <<< ИЗМЕНЕННЫЙ ИМПОРТ

logger = get_logger(__name__)
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


async def _process_dislocation_file(filepath: str):
    """
    Обновляет таблицу tracking и запускает анализ на наличие новых событий поезда.
    """
    try:
        df = pd.read_excel(filepath, skiprows=3)
        df.columns = [str(c).strip() for c in df.columns]

        if "Номер контейнера" not in df.columns:
            raise ValueError("В файле дислокации отсутствует колонка 'Номер контейнера'")

        records_to_insert = []
        for _, row in df.iterrows():
            try:
                km_raw = row.get("Расстояние оставшееся", 0)
                km_left = int(float(km_raw)) if pd.notna(km_raw) and km_raw != "" else 0
            except (ValueError, TypeError):
                km_left = 0

            record = {
                "container_number": str(row["Номер контейнера"]).strip().upper(),
                "from_station": str(row.get("Станция отправления", "")).strip(),
                "to_station": str(row.get("Станция назначения", "")).strip(),
                "current_station": str(row.get("Станция операции", "")).strip(),
                "operation": str(row.get("Операция", "")).strip(),
                "operation_date": str(row.get("Дата и время операции", "")).strip(),
                "waybill": str(row.get("Номер накладной", "")).strip(),
                "km_left": km_left,
                "forecast_days": round(km_left / 600, 1) if km_left else 0.0,
                "wagon_number": str(row.get("Номер вагона", "")).strip(),
                "operation_road": str(row.get("Дорога операции", "")).strip(),
            }
            records_to_insert.append(record)

        # Сначала обновляем основную базу, чтобы все данные были актуальны
        async with SessionLocal() as session:
            async with session.begin():
                await session.execute(text("TRUNCATE TABLE tracking"))
                if records_to_insert:
                    await session.execute(Tracking.__table__.insert(), records_to_insert)
        
        logger.info(f"✅ Таблица 'tracking' успешно обновлена. Записей: {len(records_to_insert)}.")
        
        # Теперь, когда база обновлена, запускаем анализ на наличие событий
        if records_to_insert:
            await process_dislocation_for_train_events(records_to_insert)

    except Exception as e:
        logger.error(f"❌ Ошибка обработки файла дислокации {filepath}: {e}", exc_info=True)
        raise


async def check_and_process_dislocation():
    """
    Основная функция: ищет самый свежий файл дислокации на почте и обрабатывает его.
    Игнорирует файлы 'Executive summary'.
    """
    logger.info("📬 [Dislocation] Начинаю проверку почты на наличие файлов дислокации...")
    imap = ImapService()
    
    filepath = await asyncio.to_thread(
        imap.download_latest_attachment,
        criteria='ALL',
        download_folder=DOWNLOAD_FOLDER
    )

    if not filepath:
        logger.info("[Dislocation] Новых файлов дислокации на почте не найдено.")
        return

    filename_lower = os.path.basename(filepath).lower()
    if "executive summary" in filename_lower or "a-terminal" in filename_lower:
        logger.info(f"[Dislocation] Файл '{os.path.basename(filepath)}' пропущен, так как это отчет терминала.")
        return

    await _process_dislocation_file(filepath)