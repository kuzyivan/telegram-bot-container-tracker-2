# services/container_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple, Iterable

import pandas as pd
from sqlalchemy import text

from db import SessionLocal
from logger import get_logger

logger = get_logger(__name__)


# ───────────────────────────────────────────────────────────────────────────────
# Утилиты (без изменений)
# ───────────────────────────────────────────────────────────────────────────────

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


# ───────────────────────────────────────────────────────────────────────────────
# Импорт Executive summary → terminal_containers (ИСПРАВЛЕНО)
# ───────────────────────────────────────────────────────────────────────────────

async def import_loaded_and_dispatch_from_excel(file_path: str) -> Tuple[int, int]:
    """
    Импорт из отчёта Executive summary.
    Возвращает (added_total, processed_sheets)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    xls = pd.ExcelFile(file_path)
    sheet_names = xls.sheet_names
    target_sheets = [
        s for s in sheet_names
        if str(s).strip().lower().startswith(("dispatch", "loaded"))
    ]

    added_total = 0
    processed = 0

    async with SessionLocal() as session:
        for sheet in target_sheets:
            try:
                df = pd.read_excel(file_path, sheet_name=sheet)
                col = find_container_column(df)
                if not col:
                    logger.warning(f"[Executive summary] На листе '{sheet}' не найден столбец с контейнерами.")
                    continue

                values = [normalize_container(v) for v in df[col].dropna().tolist()]
                containers = [v for v in values if v]

                if not containers:
                    processed += 1
                    continue

                for cn in containers:
                    # ИСПРАВЛЕНИЕ 1: Используем 'RETURNING id'
                    # Это современный и надежный способ узнать, была ли реально добавлена новая запись.
                    # Запрос теперь просит БД вернуть 'id' вставленной строки. Если строка не была
                    # вставлена (из-за ON CONFLICT), результат будет пустым.
                    res = await session.execute(
                        text("""
                            INSERT INTO terminal_containers (container_number)
                            VALUES (:cn)
                            ON CONFLICT (container_number) DO NOTHING
                            RETURNING id
                        """),
                        {"cn": cn},
                    )
                    # Если результат .scalar_one_or_none() не None, значит, вставка произошла.
                    if res.scalar_one_or_none() is not None:
                        added_total += 1

                await session.commit()
                processed += 1

            except Exception as e:
                logger.exception(f"[Executive summary] Ошибка обработки листа '{sheet}': {e}")

    logger.info(f"📥 Импорт Executive summary: листов обработано={processed}, добавлено новых контейнеров={added_total}")
    return added_total, processed


# ───────────────────────────────────────────────────────────────────────────────
# Импорт «поездных» файлов → terminal_containers.train (ИСПРАВЛЕНО)
# ───────────────────────────────────────────────────────────────────────────────

async def import_train_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Импорт ручного файла с контейнерами, отправленными поездом.
    Возвращает (updated_count, containers_total, train_code).
    """
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
            # ИСПРАВЛЕНИЕ 2: Используем '# type: ignore'
            # Для команды UPDATE атрибут .rowcount является документированным и правильным способом
            # узнать количество обновленных строк. Pylance ошибается, так как общая типизация
            # Result не гарантирует его наличие. Мы "успокаиваем" Pylance, говоря,
            # что мы уверены в наличии этого атрибута в данном контексте.
            updated_sum += res.rowcount  # type: ignore

        await session.commit()

    logger.info(f"🚆 Проставлен поезд {train_code}: обновлено {updated_sum} из {total} контейнеров "
                f"({os.path.basename(src_file_path)})")
    return updated_sum, total, train_code