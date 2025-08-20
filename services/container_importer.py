import os
import pandas as pd
from datetime import datetime
from sqlalchemy import select
from db import SessionLocal
from model.terminal_container import TerminalContainer
from logger import get_logger

logger = get_logger(__name__)

async def import_loaded_and_dispatch_from_excel(filepath: str):
    """
    Импортирует данные из листов Loaded* и Dispatch* Excel-файла и сохраняет новые записи в БД.
    """
    logger.info(f"📊 Импорт из Excel: {filepath}")
    sheet_names = pd.ExcelFile(filepath).sheet_names

    async with SessionLocal() as session:
        added_count = 0

        for sheet in sheet_names:
            if not (sheet.lower().startswith("loaded") or sheet.lower().startswith("dispatch")):
                continue

            logger.info(f"🔍 Обработка листа: {sheet}")
            try:
                df = pd.read_excel(filepath, sheet_name=sheet)

                for _, row in df.iterrows():
                    container_number = str(row.get("Контейнер")).strip().upper()
                    if not container_number or container_number == "nan":
                        continue

                    # Проверка на наличие в базе
                    exists = await session.execute(
                        select(TerminalContainer).where(TerminalContainer.container_number == container_number)
                    )
                    if exists.scalar_one_or_none():
                        continue  # уже в базе

                    new_record = TerminalContainer(
                        container_number=container_number,
                        terminal=str(row.get("Терминал")).strip(),
                        zone=str(row.get("Зона")).strip(),
                        inn=str(row.get("ИНН")).strip(),
                        short_name=str(row.get("Краткое наименование")).strip(),
                        client=str(row.get("Клиент")).strip(),
                        stock=str(row.get("Сток")).strip(),
                        customs_mode=str(row.get("Таможенный режим")).strip(),
                        destination_station=str(row.get("Направление")).strip(),
                        note=str(row.get("Примечание")).strip(),
                        raw_comment=str(row.get("Unnamed: 36")).strip(),
                        status_comment=str(row.get("Unnamed: 37")).strip(),
                        created_at=datetime.utcnow()
                    )

                    session.add(new_record)
                    added_count += 1

                logger.info(f"✅ {sheet}: добавлено {added_count} новых контейнеров")

            except Exception as e:
                logger.warning(f"⚠️ Ошибка при обработке листа {sheet}: {e}")

        await session.commit()
        logger.info(f"📥 Импорт завершён. Всего добавлено: {added_count}")