# services/container_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple, Iterable
import json

import pandas as pd
from sqlalchemy import text


from db import SessionLocal
from logger import get_logger

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Утилиты
# -----------------------------------------------------------------------------

def extract_train_code_from_filename(filename: str) -> str | None:
    name = os.path.basename(filename)
    m = re.search(r"К\d{2}-\d{3}", name, flags=re.IGNORECASE)
    if not m:
        return None
    code = m.group(0)
    code = "К" + code[1:]
    return code


def normalize_container(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s or s == "NAN":
        return None
    s = re.sub(r"\s+", "", s)
    return s

def find_container_column(df: pd.DataFrame) -> str | None:
    # Ищем колонку с названием 'Контейнер' или похожим
    for col in df.columns:
        c = str(col).strip().lower()
        if c in ["контейнер", "container", "container #"]:
            return col
    return None


async def _collect_containers_from_excel(file_path: str) -> List[str]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    xls = pd.ExcelFile(file_path)
    containers: List[str] = []

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except Exception:
            continue
        col = find_container_column(df)
        if not col:
            continue

        vals = [normalize_container(v) for v in df[col].dropna().tolist()]
        vals = [v for v in vals if v]
        containers.extend(vals)

    seen = set()
    uniq: List[str] = []
    for c in containers:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _chunks(seq: Iterable[str], size: int) -> Iterable[List[str]]:
    buf: List[str] = []
    for x in seq:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf

# -----------------------------------------------------------------------------
# ИТОГОВАЯ ВЕРСИЯ ФУНКЦИИ ИМПОРТА
# -----------------------------------------------------------------------------

async def import_loaded_and_dispatch_from_excel(file_path: str) -> Tuple[int, int]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    # Точное соответствие колонок из вашего файла Excel колонкам в БД
    COLUMN_MAP = {
        'Терминал': 'terminal',
        'Зона': 'zone',
        'Клиент': 'client',
        'Сток': 'stock',
        'Таможенный режим': 'customs_mode',
        'Направление': 'destination_station',
        'Примечание': 'note',
    }

    xls = pd.ExcelFile(file_path)
    target_sheets = [
        s for s in xls.sheet_names
        if str(s).strip().lower().startswith(("dispatch", "loaded"))
    ]

    total_changed = 0
    processed_sheets = 0

    async with SessionLocal() as session:
        for sheet in target_sheets:
            try:
                df = pd.read_excel(file_path, sheet_name=sheet)
                df.columns = [str(c).strip() for c in df.columns]
                
                container_col_name = find_container_column(df)
                if not container_col_name:
                    logger.warning(f"[Executive summary] На листе '{sheet}' не найден столбец с контейнерами.")
                    continue

                db_cols_to_update = [db_col for xl_col, db_col in COLUMN_MAP.items() if xl_col in df.columns]
                
                records_to_upsert = []
                for _, row in df.iterrows():
                    container_num = normalize_container(row.get(container_col_name))
                    if not container_num:
                        continue
                    
                    record = {'container_number': container_num}
                    for xl_col, db_col in COLUMN_MAP.items():
                        if xl_col in row:
                            value = row[xl_col]
                            record[db_col] = '' if pd.isna(value) else str(value)
                    
                    records_to_upsert.append(record)

                if not records_to_upsert:
                    processed_sheets += 1
                    continue
                
                all_db_columns = ['container_number'] + db_cols_to_update
                
                if not db_cols_to_update:
                    stmt = text("""
                        INSERT INTO terminal_containers (container_number)
                        SELECT (json_array_elements_text(:records)::json->>'container_number')
                        ON CONFLICT (container_number) DO NOTHING;
                    """)
                    records_json = json.dumps(records_to_upsert)
                else:
                    update_clause = "UPDATE SET " + ", ".join([f"{col} = EXCLUDED.{col}" for col in db_cols_to_update])
                    records_json = json.dumps([
                        {k: v for k, v in rec.items() if k in all_db_columns} 
                        for rec in records_to_upsert
                    ])
                    stmt = text(f"""
                        INSERT INTO terminal_containers ({", ".join(all_db_columns)})
                        SELECT p.*
                        FROM json_populate_recordset(null::terminal_containers, :records) AS p
                        ON CONFLICT (container_number) DO {update_clause};
                    """)

                res = await session.execute(stmt, {'records': records_json})
                total_changed += res.rowcount or 0 # type: ignore
                
                await session.commit()
                processed_sheets += 1

            except Exception as e:
                logger.error(f"[Executive summary] Ошибка обработки листа '{sheet}': {e}", exc_info=True)

    logger.info(f"📥 Импорт Executive summary: листов обработано={processed_sheets}, обновлено/добавлено записей={total_changed}")
    return total_changed, processed_sheets


# -----------------------------------------------------------------------------
# Импорт «поездных» файлов
# -----------------------------------------------------------------------------

async def import_train_excel(src_file_path: str) -> Tuple[int, int, str]:
    if not os.path.exists(src_file_path):
        raise FileNotFoundError(src_file_path)

    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError("Не удалось извлечь код поезда из имени файла. Ожидается шаблон 'КДД-ННН'.")

    containers = await _collect_containers_from_excel(src_file_path)
    total = len(containers)
    if total == 0:
        logger.info(f"[Train] В файле нет контейнеров: {os.path.basename(src_file_path)}")
        return 0, 0, train_code

    updated_sum = 0
    async with SessionLocal() as session:
        for chunk in _chunks(containers, 500):
            res = await session.execute(
                text("""
                    UPDATE terminal_containers
                       SET train = :train
                     WHERE container_number = ANY(:cn_list)
                """),
                {"train": train_code, "cn_list": chunk},
            )
            updated_sum += res.rowcount or 0 # type: ignore

        await session.commit()

    logger.info(f"🚆 Проставлен поезд {train_code}: обновлено {updated_sum} из {total} контейнеров "
                f"({os.path.basename(src_file_path)})")
    return updated_sum, total, train_code