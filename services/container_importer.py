# services/container_importer.py
import os
import pandas as pd
from datetime import datetime
from sqlalchemy import select
from db import SessionLocal
from model.terminal_container import TerminalContainer
from logger import get_logger

logger = get_logger(__name__)

def _to_str(x: object) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return "" if s.lower() == "nan" else s

async def import_loaded_and_dispatch_from_excel(filepath: str):
    """
    Импортирует данные из листов Loaded* и Dispatch* Excel-файла и ДОБАВЛЯЕТ только новые контейнеры.
    Ничего не удаляет.
    """
    logger.info(f"📊 Импорт из Excel: {filepath}")
    xls = pd.ExcelFile(filepath)
    sheet_names = xls.sheet_names

    total_added = 0
    async with SessionLocal() as session:
        for sheet in sheet_names:
            name_low = sheet.lower()
            if not (name_low.startswith("loaded") or name_low.startswith("dispatch")):
                continue

            logger.info(f"🔍 Обработка листа: {sheet}")
            try:
                df = pd.read_excel(filepath, sheet_name=sheet)

                added_this_sheet = 0
                for _, row in df.iterrows():
                    container_number = _to_str(
                        row.get("Контейнер")
                        or row.get("Container")
                        or row.get("Номер контейнера")
                    ).upper()

                    if not container_number:
                        continue

                    # Проверка наличия
                    exists_q = await session.execute(
                        select(TerminalContainer).where(
                            TerminalContainer.container_number == container_number
                        )
                    )
                    if exists_q.scalar_one_or_none():
                        continue

                    rec = TerminalContainer(
                        container_number=container_number,
                        terminal=_to_str(row.get("Терминал")),
                        zone=_to_str(row.get("Зона")),
                        inn=_to_str(row.get("ИНН")),
                        short_name=_to_str(row.get("Краткое наименование")),
                        client=_to_str(row.get("Клиент")),
                        stock=_to_str(row.get("Сток")),
                        customs_mode=_to_str(row.get("Таможенный режим")),
                        destination_station=_to_str(row.get("Направление")),
                        note=_to_str(row.get("Примечание")),
                        raw_comment=_to_str(row.get("Unnamed: 36")),
                        status_comment=_to_str(row.get("Unnamed: 37")),
                        created_at=datetime.utcnow(),
                    )
                    session.add(rec)
                    added_this_sheet += 1
                    total_added += 1

                # Коммит по листу
                await session.commit()
                logger.info(f"✅ {sheet}: добавлено новых контейнеров: {added_this_sheet}")

            except Exception as e:
                logger.warning(f"⚠️ Ошибка при обработке листа {sheet}: {e}", exc_info=True)

    logger.info(f"📥 Импорт завершён. Всего добавлено: {total_added}")