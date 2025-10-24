# queries/train_queries.py
"""
Запросы SQLAlchemy для получения информации о поездах и связанных контейнерах.
"""
from sqlalchemy import select, func, desc, distinct # <<< ДОБАВЛЕН distinct
from sqlalchemy.orm import aliased
from typing import List

from db import SessionLocal
# ✅ Исправляем импорт TerminalContainer
from models import Tracking
from model.terminal_container import TerminalContainer
from logger import get_logger

logger = get_logger(__name__)

# =====================================================================
# НОВАЯ ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ СПИСКА ПОЕЗДОВ (Исправлен тип возврата)
# =====================================================================

async def get_all_train_codes() -> List[str]:
    """
    Получает список всех уникальных, непустых номеров поездов 
    из таблицы TerminalContainer.
    """
    async with SessionLocal() as session:
        # Фильтруем пустые значения (None и пустая строка) прямо в запросе
        result = await session.execute(
            select(distinct(TerminalContainer.train))
            .where(TerminalContainer.train.isnot(None), TerminalContainer.train != '')
            .order_by(TerminalContainer.train)
        )
        # SQLAlchemy вернет список str, поскольку мы отфильтровали None и ''
        train_codes = result.scalars().all()
        
        # NOTE: Несмотря на фильтр в .where(), Pylance может требовать 
        # дополнительной фильтрации в Python, если не может полностью доверять 
        # SQL-типизации. Однако в этом случае достаточно, чтобы запрос был точным. 
        # Если ошибка сохраняется, используйте list(filter(None, train_codes)) 
        # или List[str | None].
        
        # Для соответствия типу List[str] используем list(train_codes)
        final_list: List[str] = list(train_codes) 
        
        logger.info(f"Найдено {len(final_list)} уникальных номеров поездов.")
        return final_list # <<< ИСПРАВЛЕНО: возвращаем гарантированный List[str]

# =====================================================================
# КОНЕЦ НОВОЙ ФУНКЦИИ
# =====================================================================


async def get_train_client_summary_by_code(train_code: str) -> dict[str, int]:
    """
    Получает сводку по клиентам для указанного поезда.
    Возвращает словарь {клиент: количество_контейнеров}.
    """
    summary = {}
    async with SessionLocal() as session:
        # Выбираем контейнеры на терминале с нужным номером поезда
        # и группируем по клиенту, считая количество контейнеров
        result = await session.execute(
            select(TerminalContainer.client, func.count(TerminalContainer.id).label('count'))
            .where(TerminalContainer.train == train_code)
            .group_by(TerminalContainer.client)
            .order_by(func.count(TerminalContainer.id).desc()) # Сортируем по убыванию количества
        )
        rows = result.mappings().all() # Получаем результат как список словарей
        
        # Преобразуем результат в нужный формат
        summary = {row['client'] if row['client'] else 'Не указан': row['count'] for row in rows}
        
    if summary:
         logger.info(f"Найдена сводка для поезда {train_code}: {len(summary)} клиентов.")
    else:
         logger.warning(f"Сводка для поезда {train_code} не найдена (нет контейнеров с таким поездом в terminal_containers).")
         
    return summary


async def get_first_container_in_train(train_code: str) -> str | None:
     """
     Находит номер первого попавшегося контейнера в указанном поезде
     из таблицы terminal_containers (для получения примера дислокации).
     """
     async with SessionLocal() as session:
         result = await session.execute(
             select(TerminalContainer.container_number)
             .where(TerminalContainer.train == train_code)
             .limit(1)
         )
         container = result.scalar_one_or_none()
         if container:
             logger.debug(f"Найден пример контейнера {container} для поезда {train_code}")
         else:
              logger.debug(f"Не найден пример контейнера для поезда {train_code} в terminal_containers")
         return container

# --- Старые/Ненужные функции (можно удалить, если не используются) ---

# async def get_train_summary(train_no: str) -> dict[str, int]:
#     """ (Устарело?) Получает сводку по клиентам для поезда """
#     # Реализация похожа на get_train_client_summary_by_code
#     pass 

# async def get_train_latest_status(train_no: str) -> Optional[tuple[str, str, str]]:
#     """ (Устарело?) Получает последний статус поезда по одному из его контейнеров """
#     # Эта логика теперь, вероятно, внутри train.py (_get_full_train_report_text)
#     pass