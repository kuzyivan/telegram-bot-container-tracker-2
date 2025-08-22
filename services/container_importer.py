# services/train_importer.py
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple, Set

import pandas as pd
from sqlalchemy import select
from logger import get_logger

from model.terminal_container import TerminalContainer
from db import SessionLocal  # async session factory

logger = get_logger(__name__)

# Куда складываем «поездные» файлы, если хотим их хранить
TRAIN_DOWNLOAD_DIR = "/root/AtermTrackBot/download_train"
os.makedirs(TRAIN_DOWNLOAD_DIR, exist_ok=True)

# Имена возможных колонок с номером контейнера (в Excel может быть по‑разному)
CONTAINER_COL_CANDIDATES = {
    "номер контейнера",
    "контейнер",
    "container",
    "container number",
    "container_no",
    "container no",
    "№ контейнера",
    "номер",
}


def extract_train_code_from_filename(filename: str) -> str | None:
    """
    Извлекаем код поезда из имени файла.
    Примеры:
      - 'КП К25-073 Селятино.xlsx' -> 'К25-073'
      - допускаем латинскую K: 'КП K25-073 ...' -> 'K25-073'
    Шаблон: буква К/К (кирилл/латин), 2 цифры, тире, 3 цифры.
    """
    name = Path(filename).stem
    m = re.search(r"\b[КK]\d{2}-\d{3}\b", name, flags=re.IGNORECASE)
    if not m:
        return None
    # Сохраняем как найдено (регистр и буква)
    return m.group(0)


def normalize_container(value) -> str | None:
    """
    Нормализуем номер контейнера: upper, убираем пробелы и невидимые символы.
    Возвращаем None, если пусто/NaN.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    s = re.sub(r"\s+", "", s)
    if s in ("", "NAN", "NONE"):
        return None
    return s


def find_container_column(df: pd.DataFrame) -> str | None:
    """
    Пытаемся найти колонку с номером контейнера по набору кандидатов.
    Сравнение — по нижнему регистру, без лишних пробелов.
    """
    normalized = {c.lower().strip(): c for c in df.columns}
    for cand in CONTAINER_COL_CANDIDATES:
        if cand in normalized:
            return normalized[cand]
    # иногда в файлах встречаются похожие варианты — ищем частичное совпадение
    for key_lower, original in normalized.items():
        if "контейн" in key_lower or "contain" in key_lower:
            return original
    return None


async def _collect_containers_from_excel(file_path: str) -> List[str]:
    """
    Читает все листы Excel и собирает контейнеры из найденной колонки.
    Дубликаты выбрасываются, возвращаем список нормализованных номеров.
    """
    xls = pd.ExcelFile(file_path)
    containers: Set[str] = set()

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except Exception as e:
            logger.warning("⚠️ Не удалось прочитать лист '%s': %s", sheet, e)
            continue

        if df.empty:
            continue

        col = find_container_column(df)
        if not col:
            logger.debug("На листе '%s' колонка с контейнером не найдена.", sheet)
            continue

        for v in df[col].tolist():
            cn = normalize_container(v)
            if cn:
                containers.add(cn)

    return sorted(containers)


async def import_train_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Главная функция:
      - извлекает код поезда из имени файла,
      - копирует файл в TRAIN_DOWNLOAD_DIR (как архивную копию),
      - читает контейнеры,
      - обновляет terminal_containers.train для всех найденных контейнеров.

    Возвращает (updated_count, not_found_count, train_code).
    """
    # 1) Извлекаем номер поезда
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(
            "Не удалось извлечь номер поезда из имени файла. "
            "Ожидается шаблон вроде 'К25-073' (К/К, 2 цифры, '-', 3 цифры)."
        )
    logger.info("🚂 Определён поезд: %s (из '%s')", train_code, src_file_path)

    # 2) Копируем файл в download_train для архива (не критично, можно пропустить)
    try:
        dst_name = Path(src_file_path).name
        dst_path = str(Path(TRAIN_DOWNLOAD_DIR) / dst_name)
        if os.path.abspath(src_file_path) != os.path.abspath(dst_path):
            # копируем содержимое
            with open(src_file_path, "rb") as r, open(dst_path, "wb") as w:
                w.write(r.read())
        logger.info("📦 Файл сохранён: %s", dst_path)
    except Exception as e:
        logger.warning("⚠️ Не удалось сохранить архивную копию файла: %s", e)

    # 3) Собираем контейнеры из Excel
    containers = await _collect_containers_from_excel(src_file_path)
    if not containers:
        logger.info("🛈 В файле не найдено контейнеров. Нечего обновлять.")
        return (0, 0, train_code)

    logger.info("🔍 В файле найдено контейнеров: %d", len(containers))

    # 4) Обновляем базу
    updated = 0
    not_found = 0

    async with SessionLocal() as session:
        # Сразу вытягиваем все, что есть в БД
        stmt = select(TerminalContainer).where(TerminalContainer.container_number.in_(containers))
        res = await session.execute(stmt)
        found_objects: List[TerminalContainer] = list(res.scalars())

        found_set = {obj.container_number for obj in found_objects}
        missing_set = set(containers) - found_set

        # Проставляем поезд существующим
        for obj in found_objects:
            obj.train = train_code
        updated = len(found_objects)

        # Фиксируем изменения
        await session.commit()

        not_found = len(missing_set)

    logger.info("✅ Импорт поездов завершён: обновлено %d, не найдено в БД %d. Поезд: %s",
                updated, not_found, train_code)
    if not_found:
        logger.debug("Не найденные контейнеры (первые 20): %s",
                     ", ".join(list(missing_set)[:20]))

    return (updated, not_found, train_code)


# Удобный CLI-хелпер:
#   python -m services.train_importer "/path/КП К25-073 Селятино.xlsx"
if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m services.train_importer \"/path/КП К25-073 Селятино.xlsx\"")
        raise SystemExit(1)

    path = sys.argv[1]
    if not Path(path).is_file():
        print(f"Файл не найден: {path}")
        raise SystemExit(1)

    updated, not_found, train = asyncio.run(import_train_excel(path))
    print(f"Готово. Поезд {train}: обновлено {updated}, не найдено {not_found}.")