# services/train_importer.py
from __future__ import annotations

import os
import re
from typing import List, Tuple, Dict, Any
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from logger import get_logger
from model.terminal_container import TerminalContainer
from db import SessionLocal 

logger = get_logger(__name__)

TRAIN_FOLDER = "/root/AtermTrackBot/download_train"
os.makedirs(TRAIN_FOLDER, exist_ok=True)

# Индекс колонки Клиента (L-колонка = 11-й индекс, т.к. индексация с 0)
CLIENT_COLUMN_INDEX = 11 

# --- Вспомогательные функции ---

def extract_train_code_from_filename(filename: str) -> str | None:
    """Извлекаем код поезда из имени файла."""
    if not filename: return None
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    m = re.search(r"([КK]\s*\d{2}[-–— ]?\s*\d{3})", name, flags=re.IGNORECASE)
    if not m: return None
    code = m.group(1).upper().replace("K", "К").replace(" ", "").replace("–", "-").replace("—", "-")
    return code


def normalize_container(value) -> str | None:
    """Нормализует номер контейнера, обрабатывая float."""
    if pd.isna(value) or value is None: return None
    s = str(value).strip().upper()
    if s.endswith('.0'): s = s[:-2]
    return s if s else None


def find_container_column(df: pd.DataFrame) -> str | None:
    """Пытаемся найти колонку с номерами контейнеров."""
    candidates = ["контейнер", "container", "container no", "container no.", 
                  "номер контейнера", "№ контейнера", "номенклатура"]
    cols_norm = {str(c).strip().lower(): c for c in df.columns}
    
    for cand in candidates:
        if cand in cols_norm: return cols_norm[cand]
    
    for col in df.columns:
        name = str(col).strip().lower()
        if name.startswith("contain") or "контейнер" in name: return col
            
    return None

def normalize_client_name(value) -> str | None:
    """Нормализует имя клиента."""
    if pd.isna(value) or value is None: return None
    s = str(value).strip()
    return s if s else None


async def _collect_containers_from_excel(file_path: str) -> Dict[str, str]:
    """
    Читает Excel и возвращает словарь {container_number: client_name}.
    """
    xl = pd.ExcelFile(file_path)
    container_client_map: Dict[str, str] = {}
    
    # ⚠️ ПРЕДПОЛОЖЕНИЕ: Заголовки находятся в первой строке (header=0) после skiprows=0
    # и CLIENT_COLUMN_INDEX (11) указывает на колонку с клиентом.

    for sheet in xl.sheet_names:
        try:
            # Читаем Excel, предполагая, что первая строка содержит заголовки
            df = pd.read_excel(xl, sheet_name=sheet) 
            df.columns = [str(c).strip() for c in df.columns]
            
            # Находим заголовок для контейнера
            container_col_header = find_container_column(df)
            
            # Находим заголовок для клиента (используем индекс 11 - L)
            if CLIENT_COLUMN_INDEX >= len(df.columns):
                logger.warning(f"[train_importer] На листе '{sheet}' нет колонки {CLIENT_COLUMN_INDEX} (Клиент). Пропускаю.")
                continue
                
            client_col_header = df.columns[CLIENT_COLUMN_INDEX]

            if not container_col_header:
                logger.warning(f"[train_importer] На листе '{sheet}' не найдена колонка контейнеров. Пропускаю.")
                continue

            for _, row in df.iterrows():
                cn = normalize_container(row.get(container_col_header))
                client = normalize_client_name(row.get(client_col_header))
                
                if cn and client:
                    container_client_map[cn] = client
        except Exception as e:
            logger.error(f"[train_importer] Ошибка при чтении листа '{sheet}': {e}", exc_info=True)

    return container_client_map


async def import_train_from_excel(src_file_path: str) -> Tuple[int, int, str]:
    """
    Проставляет номер поезда и клиента в terminal_containers.
    """
    train_code = extract_train_code_from_filename(src_file_path)
    if not train_code:
        raise ValueError(
            f"Не удалось извлечь номер поезда из имени файла: {os.path.basename(src_file_path)}"
        )

    container_client_map = await _collect_containers_from_excel(src_file_path)
    total_in_file = len(container_client_map)

    if total_in_file == 0:
        logger.warning(f"[train_importer] В файле нет распознанных контейнеров: {os.path.basename(src_file_path)}")
        return 0, 0, train_code

    updated = 0
    try:
        async with SessionLocal() as session:
            
            for cn, client_name in container_client_map.items():
                
                # ✅ ИСПРАВЛЕНИЕ: Обновляем и 'train', и 'client'
                update_stmt = update(TerminalContainer).where(
                    TerminalContainer.container_number == cn
                ).values(
                    train=train_code,
                    client=client_name  # <-- ДОБАВЛЕНО ПОЛЕ КЛИЕНТ
                )
                
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