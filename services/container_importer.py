# services/container_importer.py
import pandas as pd
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert
from db import SessionLocal
from model.terminal_container import TerminalContainer
from logger import get_logger

logger = get_logger(__name__)

def _s(val):
    # Безопасное приведение: None/NaN -> None, строка -> .strip()
    if val is None or (isinstance(val, float) and pd.isna(val)) or (isinstance(val, str) and val.strip().lower() == 'nan'):
        return None
    return str(val).strip()

async def import_loaded_and_dispatch_from_excel(filepath: str):
    """
    Импортирует данные из листов Loaded* и Dispatch* Excel-файла в terminal_containers.
    Дубликаты по container_number игнорируются на уровне БД (ON CONFLICT DO NOTHING).
    """
    logger.info(f"📊 Импорт из Excel: {filepath}")
    xls = pd.ExcelFile(filepath)
    sheet_names = xls.sheet_names

    added_total = 0

    async with SessionLocal() as session:
        for sheet in sheet_names:
            if not (sheet.lower().startswith("loaded") or sheet.lower().startswith("dispatch")):
                continue

            logger.info(f"🔍 Обработка листа: {sheet}")
            try:
                df = pd.read_excel(filepath, sheet_name=sheet)

                # Название столбцов из вашего файла
                # Подправьте, если где-то отличаются:
                col = {
                    "container": "Контейнер",
                    "terminal": "Терминал",
                    "zone": "Зона",
                    "inn": "ИНН",
                    "short_name": "Краткое наименование",
                    "client": "Клиент",
                    "stock": "Сток",
                    "customs_mode": "Таможенный режим",
                    "dest": "Направление",
                    "note": "Примечание",
                    "raw_comment": "Unnamed: 36",
                    "status_comment": "Unnamed: 37",
                }

                added_sheet = 0
                for _, row in df.iterrows():
                    cn = _s(row.get(col["container"]))
                    if not cn:
                        continue
                    cn = cn.upper()

                    payload = {
                        "container_number": cn,
                        "terminal": _s(row.get(col["terminal"])),
                        "zone": _s(row.get(col["zone"])),
                        "inn": _s(row.get(col["inn"])),
                        "short_name": _s(row.get(col["short_name"])),
                        "client": _s(row.get(col["client"])),
                        "stock": _s(row.get(col["stock"])),
                        "customs_mode": _s(row.get(col["customs_mode"])),
                        "destination_station": _s(row.get(col["dest"])),
                        "note": _s(row.get(col["note"])),
                        "raw_comment": _s(row.get(col["raw_comment"])),
                        "status_comment": _s(row.get(col["status_comment"])),
                        "created_at": datetime.utcnow(),
                    }

                    # UPSERT: вставить, если нет — иначе молча пропустить
                    stmt = (
                        insert(TerminalContainer)
                        .values(**payload)
                        .on_conflict_do_nothing(index_elements=[TerminalContainer.container_number])
                    )
                    res = await session.execute(stmt)
                    # res.rowcount == 1 если вставили, 0 если пропустили
                    if getattr(res, "rowcount", 0) == 1:
                        added_sheet += 1
                        added_total += 1

                await session.commit()
                logger.info(f"✅ {sheet}: добавлено {added_sheet} новых контейнеров")

            except Exception as e:
                # На всякий пожарный — откат листа и лог
                await session.rollback()
                logger.warning(f"⚠️ Ошибка при обработке листа {sheet}: {e}", exc_info=True)

    logger.info(f"📥 Импорт завершён. Всего добавлено: {added_total}")