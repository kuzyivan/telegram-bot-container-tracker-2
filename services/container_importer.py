# services/container_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple, Iterable
import json

import pandas as pd
from sqlalchemy import text, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert


from db import SessionLocal
from logger import get_logger
from models import TerminalContainer

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Утилиты (без изменений)
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
# ФИНАЛЬНАЯ ВЕРСИЯ ФУНКЦИИ ИМПОРТА
# -----------------------------------------------------------------------------

async def import_loaded_and_dispatch_from_excel(file_path: str) -> Tuple[int, int]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    COLUMN_MAP = {
        'Терминал': 'terminal', 'Зона': 'zone', 'Клиент': 'client',
        'Сток': 'stock', 'Таможенный режим': 'customs_mode',
        'Направление': 'destination_station', 'Примечание': 'note',
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

                for _, row in df.iterrows():
                    container_num = normalize_container(row.get(container_col_name))
                    if not container_num:
                        continue
                    
                    # Собираем данные для вставки/обновления
                    data_to_upsert = {'container_number': container_num}
                    for xl_col, db_col in COLUMN_MAP.items():
                        if xl_col in row:
                            value = row[xl_col]
                            data_to_upsert[db_col] = '' if pd.isna(value) else str(value)
                    
                    # Используем конструктор запросов SQLAlchemy - это надёжнее
                    stmt = pg_insert(TerminalContainer).values(data_to_upsert)
                    
                    # Определяем, какие поля обновлять при конфликте
                    update_data = {k: v for k, v in data_to_upsert.items() if k != 'container_number'}
                    
                    # Добавляем ON CONFLICT ... DO UPDATE
                    # Это сработает, только если есть что обновлять
                    if update_data:
                        stmt = stmt.on_conflict_do_update(
                            index_elements=['container_number'],
                            set_=update_data
                        )
                    else:
                        stmt = stmt.on_conflict_do_nothing(
                            index_elements=['container_number']
                        )

                    await session.execute(stmt)
                    total_changed +=1 # Считаем каждую попытку вставки/обновления

                await session.commit()
                processed_sheets += 1

            except Exception as e:
                logger.error(f"[Executive summary] Ошибка обработки листа '{sheet}': {e}", exc_info=True)
                await session.rollback()

    logger.info(f"📥 Импорт Executive summary: листов обработано={processed_sheets}, обработано записей={total_changed}")
    return total_changed, processed_sheets


# -----------------------------------------------------------------------------
# Импорт «поездных» файлов (без изменений)
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
            updated_sum += res.rowcount or 0

        await session.commit()

    logger.info(f"🚆 Проставлен поезд {train_code}: обновлено {updated_sum} из {total} контейнеров "
                f"({os.path.basename(src_file_path)})")
    return updated_sum, total, train_code