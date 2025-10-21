# services/train_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from logger import get_logger
# ✅ ИСПРАВЛЕНИЕ: Используем актуальный путь к модели
from model.terminal_container import TerminalContainer
from db import SessionLocal 

logger = get_logger(__name__)

TRAIN_FOLDER = "/root/AtermTrackBot/download_train"
os.makedirs(TRAIN_FOLDER, exist_ok=True)


def extract_train_code_from_filename(filename: str) -> str | None:
    """
    Извлекаем код поезда из имени файла вида: 'КП К25-073 Селятино.xlsx' -> 'К25-073'
    """
    if not filename: return None
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    # Ищем K или К, 2 цифры, дефис/пробел, 3 цифры
    m = re.search(r"([КK]\s*\d{2}[-–— ]?\s*\d{3})", name, flags=re.IGNORECASE)
    if not m:
        return None
    # Нормализуем формат: К25-073
    code = m.group(1).upper().replace("K", "К").replace(" ", "").replace("–", "-").replace("—", "-")
    return code


def normalize_container(value) -> str | None:
    """
    Нормализует номер контейнера, обрабатывая float и удаляя лишние символы.
    """
    if pd.isna(value) or value is None:
        return None
    
    s = str(value).strip().upper()
    
    # ✅ ИСПРАВЛЕНИЕ: Удаляем '.0' и прочие знаки, если Pandas прочитал как float
    if s.endswith('.0'):
        s = s[:-2]
        
    return s if s else None


def find_container_column(df: pd.DataFrame) -> str | None:
    """
    Пытаемся найти колонку с номерами контейнеров в Excel-файле поезда.
    """
    # ✅ ИСПРАВЛЕНИЕ: ДОБАВЛЕНЫ ВСЕ НЕОБХОДИМЫЕ КАНДИДАТЫ, включая 'Контейнер' и 'Container No.'
    candidates = [
        "контейнер", "container", "container no", "container no.", "номер контейнера", 
        "№ контейнера", "контейнера", "номенклатура"
    ]
    
    # Приводим заголовки DataFrame к нижнему регистру для поиска
    cols_norm = {str(c).strip().lower(): c for c in df.columns}
    
    for cand in candidates:
        if cand in cols_norm:
            return cols_norm[cand]
    
    # Fallback: пробуем по подстроке
    for col in df.columns:
        name = str(col).strip().lower()
        if name.startswith("contain") or "контейнер" in name: 
            return col
            
    return None


async def _collect_containers_from_excel(file_path: str) -> List[str]:
    """
    Читает Excel с контейнерами, возвращает список номеров контейнеров.
    """
    xl = pd.ExcelFile(file_path)
    containers: set[str] = set()

    for sheet in xl.sheet_names:
        try:
            # ✅ ИСПРАВЛЕНИЕ: Читаем Excel без пропуска строк (для файлов поезда)
            df = pd.read_excel(xl, sheet_name=sheet) 
            df.columns = [str(c).strip() for c in df.columns]
            
            col = find_container_column(df)
            if not col:
                logger.warning(f"[train_importer] На листе '{sheet}' не найдена колонка контейнеров. Пропускаю.")
                continue

            for _, row in df.iterrows():
                num = normalize_container(row.get(col))
                if num:
                    containers.add(num)
        except Exception as e:
            logger.error(f"[train_importer] Ошибка при чтении листа '{sheet}': {e}", exc_info=True)

    return sorted(containers)


async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Проставляет номер поезда в terminal_containers.train для всех контейнеров из файла.
    """
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(
            f"Не удалось извлечь номер поезда из имени файла: {os.path.basename(src_file_path)}"
        )

    containers = await _collect_containers_from_excel(src_file_path)
    total_in_file = len(containers)

    if total_in_file == 0:
        logger.warning(f"[train_importer] В файле нет распознанных контейнеров: {os.path.basename(src_file_path)}")
        return 0, 0, train_code

    updated = 0
    try:
        async with SessionLocal() as session:
            
            for cn in containers:
                # Обновляем поле 'train'
                update_stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == cn
                ).values(train=train_code)
                
                # NOTE: Здесь нет проверки, существует ли контейнер, 
                # но UPDATE с WHERE(container_number == cn) сам вернет rowcount=0, если его нет.
                result = await session.execute(update_stmt)
                updated += result.rowcount

            await session.commit()

        logger.info(
            f"✅ [train_importer] Поезд {train_code}: обновлено {updated} из {total_in_file} контейнеров."
        )
        return updated, total_in_file, train_code

    except SQLAlchemyError as e:
        logger.error(f"[train_importer] Ошибка БД при импорте поезда: {e}", exc_info=True)
        raise