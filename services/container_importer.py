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
# Utilities (unchanged)
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
    lowered = {str(c).strip(): str(c).strip().lower() for c in df.columns}
    keys = [
        "номер контейнера", "контейнер", "container", "container no",
        "container number", "контейнер №", "№ контейнера",
    ]
    for orig, low in lowered.items():
        if any(k in low for k in keys):
            return orig
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
# FINAL VERSION OF THE IMPORT FUNCTION
# -----------------------------------------------------------------------------

async def import_loaded_and_dispatch_from_excel(file_path: str) -> Tuple[int, int]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    COLUMN_MAP = {
        'Terminal': 'terminal', 'Zone': 'zone', 'INN': 'inn',
        'Short Name': 'short_name', 'Client': 'client', 'Stock': 'stock',
        'Customs Mode': 'customs_mode', 'Destination station': 'destination_station',
        'Note': 'note', 'Raw Comment': 'raw_comment', 'Status Comment': 'status_comment',
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
                    logger.warning(f"[Executive summary] Container column not found on sheet '{sheet}'.")
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
                
                # FINAL CORRECTED LOGIC
                all_db_columns = ['container_number'] + db_cols_to_update
                
                if not db_cols_to_update:
                    # If only container numbers are present, use a simple INSERT IGNORE
                    stmt = text("""
                        INSERT INTO terminal_containers (container_number)
                        SELECT (json_array_elements_text(:records)::json->>'container_number')
                        ON CONFLICT (container_number) DO NOTHING;
                    """)
                    records_json = json.dumps(records_to_upsert)
                else:
                    # If other columns are present, use the complex INSERT ... ON UPDATE
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
                total_changed += res.rowcount or 0
                
                await session.commit()
                processed_sheets += 1

            except Exception as e:
                logger.error(f"[Executive summary] Error processing sheet '{sheet}': {e}", exc_info=True)

    logger.info(f"📥 Executive summary import: sheets processed={processed_sheets}, records updated/added={total_changed}")
    return total_changed, processed_sheets


# -----------------------------------------------------------------------------
# Train File Import (unchanged)
# -----------------------------------------------------------------------------

async def import_train_excel(src_file_path: str) -> Tuple[int, int, str]:
    if not os.path.exists(src_file_path):
        raise FileNotFoundError(src_file_path)

    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError("Could not extract train code from filename. Expected pattern 'KDD-NNN'.")

    containers = await _collect_containers_from_excel(src_file_path)
    total = len(containers)
    if total == 0:
        logger.info(f"[Train] No containers found in file: {os.path.basename(src_file_path)}")
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
            updated_sum += res.rowcount or 0

        await session.commit()

    logger.info(f"🚆 Train {train_code} processed: updated {updated_sum} of {total} containers "
                f"({os.path.basename(src_file_path)})")
    return updated_sum, total, train_code