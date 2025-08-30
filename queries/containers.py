# queries/containers.py
from typing import Sequence
from sqlalchemy import text, select
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


async def get_latest_tracking_data(container_number: str) -> Sequence[Row]:
    """
    НОВАЯ ФУНКЦИЯ
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
        return result.fetchall()