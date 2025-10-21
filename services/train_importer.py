# services/train_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from logger import get_logger
# ✅ ИСПРАВЛЕНИЕ ЗДЕСЬ:
from model.terminal_container import TerminalContainer
from db import SessionLocal  # <-- ВАЖНО: используем SessionLocal (async sessionmaker)

logger = get_logger(__name__)

TRAIN_FOLDER = "/root/AtermTrackBot/download_train"
os.makedirs(TRAIN_FOLDER, exist_ok=True)


def extract_train_code_from_filename(filename: str) -> str | None:
    """
    Извлекаем код поезда из имени файла вида:
    'КП К25-073 Селятино.xlsx' -> 'К25-073'
    """
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    # допустим: буква К + 2 цифры + '-' + 3 цифры (или больше) — без пробелов внутри кода
    m = re.search(r"\b([КK]\d{2}-\d{3,})\b", name, flags=re.IGNORECASE)
    if m:
        # нормализуем первую букву в русскую К
        code = m.group(1).upper().replace("K", "К")
        return code
    return None


def normalize_container(value) -> str | None:
    if pd.isna(value):
        return None
    s = str(value).strip().upper()
    return s if s else None


def find_container_column(df: pd.DataFrame) -> str | None:
    """
    Пытаемся найти колонку с номерами контейнеров в Excel‑файле поезда.
    На практике чаще всего это одна из:
      - 'Номер контейнера'
      - 'Контейнер'
      - 'Container'
      - 'Контейнера'
    """
    candidates = [
        "Номер контейнера",
        "Контейнер",
        "Container",
        "Контейнера",
        "Контейнер №",
        "№ контейнера",
    ]
    cols_norm = {str(c).strip(): c for c in df.columns}
    for cand in candidates:
        if cand in cols_norm:
            return cols_norm[cand]
    # fallback: пробуем по подстроке
    for col in df.columns:
        name = str(col).strip().lower()
        if "контейнер" in name or "container" in name:
            return col
    return None


async def _collect_containers_from_excel(file_path: str) -> List[str]:
    """
    Читает Excel с отправленными в поезде контейнерами,
    возвращает список номеров контейнеров (строки в верхнем регистре).
    """
    xl = pd.ExcelFile(file_path)
    containers: set[str] = set()

    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet)
            df.columns = [str(c).strip() for c in df.columns]
            col = find_container_column(df)
            if not col:
                logger.debug(f"[train_importer] На листе '{sheet}' не найдена колонка контейнеров")
                continue

            for _, row in df.iterrows():
                num = normalize_container(row.get(col))
                if num:
                    containers.add(num)
        except Exception as e:
            logger.warning(f"[train_importer] Лист '{sheet}' пропущен: {e}")

    return sorted(containers)


async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Главная функция: берёт номер поезда из имени файла и проставляет его
    в terminal_containers.train для всех контейнеров из файла.
    Возвращает (обновлено_строк, всего_контейнеров_в_файле, train_code)
    """
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(
            f"Не удалось извлечь номер поезда из имени файла: {os.path.basename(src_file_path)}"
        )

    containers = await _collect_containers_from_excel(src_file_path)
    total_in_file = len(containers)

    if total_in_file == 0:
        logger.info(f"[train_importer] В файле нет распознанных контейнеров: {src_file_path}")
        return 0, 0, train_code

    updated = 0
    try:
        async with SessionLocal() as session:
            # Можно пакетно, но проще пройтись по списку
            for cn in containers:
                # exists?
                res = await session.execute(
                    select(TerminalContainer.id).where(TerminalContainer.container_number == cn)
                )
                row = res.first()
                if not row:
                    # контейнер из файла не найден в terminal_containers — просто пропускаем
                    continue

                await session.execute(
                    update(TerminalContainer)
                    .where(TerminalContainer.container_number == cn)
                    .values(train=train_code)
                )
                updated += 1

            await session.commit()

        logger.info(
            f"[train_importer] Поезд {train_code}: обновлено {updated} из {total_in_file} контейнеров."
        )
        return updated, total_in_file, train_code

    except SQLAlchemyError as e:
        logger.error(f"[train_importer] Ошибка БД: {e}", exc_info=True)
        raise