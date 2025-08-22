# services/train_importer.py
import re
from pathlib import Path
import pandas as pd

from sqlalchemy import update
from sqlalchemy.future import select

from logger import get_logger
from models import TerminalContainer
from db import AsyncSessionLocal  # ваш Async engine/session фабрика

logger = get_logger(__name__)

# Ищем как кириллица 'К', так и латиница 'K'
TRAIN_CODE_RE = re.compile(r'([KК]\d{2,}-\d{3})', re.IGNORECASE)

# варианты названий колонок с номером контейнера
CONTAINER_COL_CANDIDATES = [
    "номер контейнера",
    "контейнер",
    "container",
    "container number",
    "№ контейнера",
    "контейнер №",
]

def _extract_train_code_from_filename(filepath: str | Path) -> str:
    name = Path(filepath).stem  # без расширения
    m = TRAIN_CODE_RE.search(name)
    if not m:
        raise ValueError(
            f"Не удалось найти код поезда вида 'К25-073' в имени файла: {name}"
        )
    # нормализуем: большая 'К'
    code = m.group(1).upper().replace("K", "К")
    return code

def _find_container_column(df: pd.DataFrame) -> str:
    # нормализуем заголовки
    normalized = {c: str(c).strip().lower() for c in df.columns}
    # сначала ищем идеальные совпадения
    for c, norm in normalized.items():
        if norm in CONTAINER_COL_CANDIDATES:
            return c
    # затем ищем подстроки типа "контейнер"
    for c, norm in normalized.items():
        if "контейнер" in norm or "container" in norm:
            return c
    raise ValueError(
        f"Не удалось найти колонку с номером контейнера среди: {list(df.columns)}"
    )

async def import_train_from_excel(filepath: str | Path) -> tuple[int, str]:
    """
    Читает Excel с отправленными в поезде контейнерами и
    массово проставляет столбец `train` = <код из имени файла>
    для всех контейнеров из файла, которые уже есть в таблице terminal_containers.

    Возвращает: (количество обновленных строк, код_поезда)
    """
    filepath = str(filepath)
    train_code = _extract_train_code_from_filename(filepath)
    logger.info(f"🚆 Импорт поезда {train_code} из файла: {filepath}")

    # читаем первый лист как есть
    df = pd.read_excel(filepath)
    if df.empty:
        logger.warning("Пустой Excel — ничего не обновляем.")
        return 0, train_code

    col = _find_container_column(df)
    # собираем номера контейнеров
    numbers = (
        df[col]
        .dropna()
        .astype(str)
        .map(str.strip)
        .map(str.upper)
        .map(lambda s: s.replace(" ", ""))  # на всякий
        .tolist()
    )

    # удалим явные мусорные элементы
    numbers = [n for n in numbers if len(n) >= 6]  # грубый фильтр
    numbers = list(dict.fromkeys(numbers))  # уникализуем, сохраняя порядок
    if not numbers:
        logger.warning("В Excel не найдено ни одного номера контейнера.")
        return 0, train_code

    async with AsyncSessionLocal() as session:
        # Массовое обновление: train=<code> где container_number IN (...)
        # Проставляем поезд даже если там уже что-то было — это явный ручной апдейт
        result = await session.execute(
            update(TerminalContainer)
            .where(TerminalContainer.container_number.in_(numbers))
            .values(train=train_code)
            .execution_options(synchronize_session=False)
        )
        updated = result.rowcount or 0
        await session.commit()

    logger.info(f"✅ Поезд {train_code}: обновлено {updated} контейнеров.")
    return updated, train_code