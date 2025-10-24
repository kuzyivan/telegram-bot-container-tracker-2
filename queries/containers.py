# queries/containers.py
from typing import Sequence, List
from sqlalchemy import text, select, func
from sqlalchemy.engine import Row

from db import SessionLocal
from models import Tracking


async def get_latest_train_by_container(container_number: str) -> str | None:
    """
    Возвращает номер поезда (train) по самой свежей записи из terminal_containers
    для указанного контейнера.
    """
    query = text("""
        SELECT train
        FROM terminal_containers
        WHERE container_number = :c
          AND train IS NOT NULL AND train <> ''
        ORDER BY created_at DESC
        LIMIT 1
    """)
    async with SessionLocal() as session:
        res = await session.execute(query, {"c": container_number})
        return res.scalar_one_or_none()


async def get_latest_tracking_data(container_number: str) -> Sequence[Tracking]:
    """
    Находит все последние записи о дислокации для указанного контейнера
    из таблицы 'Tracking'.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(Tracking).where(
                Tracking.container_number == container_number
            ).order_by(
                Tracking.operation_date.desc()
            )
        )
        return result.scalars().all()


# <<< НАЧАЛО ФУНКЦИИ get_tracking_data_by_wagons (для фиксации: #wagon_search) >>>
async def get_tracking_data_by_wagons(wagon_numbers: List[str]) -> List[Tracking]:
    """
    Находит самые последние данные по всем контейнерам,
    которые в данный момент числятся на любом из указанных вагонов.
    """
    if not wagon_numbers:
        return []

    async with SessionLocal() as session:
        latest_ids_subquery = (
            select(func.max(Tracking.id).label("max_id"))
            .group_by(Tracking.container_number)
            .subquery()
        )
        
        # Используем .in_() для поиска по списку номеров вагонов
        query = (
            select(Tracking)
            .join(latest_ids_subquery, Tracking.id == latest_ids_subquery.c.max_id)
            .where(func.split_part(Tracking.wagon_number, '.', 1).in_(wagon_numbers))
        )
        
        result = await session.execute(query)
        
        return list(result.scalars().all())
# <<< КОНЕЦ ФУНКЦИИ get_tracking_data_by_wagons >>>