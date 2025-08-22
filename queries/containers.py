# queries/containers.py
from sqlalchemy import text
from db import SessionLocal

async def get_latest_train_by_container(container_number: str) -> str | None:
    """
    Возвращает номер поезда (train) для контейнера по самой свежей записи
    из terminal_containers. Поддерживает названия колонок `container` и `container_number`.
    """
    query = text("""
        SELECT train
        FROM terminal_containers
        WHERE (container = :c OR container_number = :c)
          AND train IS NOT NULL AND train <> ''
        ORDER BY created_at DESC
        LIMIT 1
    """)
    async with SessionLocal() as session:
        res = await session.execute(query, {"c": container_number})
        return res.scalar_one_or_none()