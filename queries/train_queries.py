from __future__ import annotations
from typing import List, Tuple, Optional
from sqlalchemy import select, func, desc, literal

from db import SessionLocal
from models import TerminalContainer, Tracking


async def get_train_summary(train_no: str) -> List[Tuple[str, int]]:
    """
    Возвращает список (client_name, cnt) для поезда train_no.
    Группируем по COALESCE(short_name, client, 'Без клиента').
    """
    async with SessionLocal() as session:
        client_expr = func.coalesce(
            TerminalContainer.short_name,
            TerminalContainer.client,
            literal("Без клиента"),
        )

        q = (
            select(
                client_expr.label("client_name"),
                func.count(func.distinct(TerminalContainer.container_number)).label("cnt"),
            )
            .where(TerminalContainer.train == train_no)
            .group_by(client_expr)
            .order_by(desc("cnt"))
        )
        rows = (await session.execute(q)).all()
        return [(r.client_name, int(r.cnt)) for r in rows]


async def get_train_latest_status(train_no: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    Возвращает кортеж:
    (container_number, operation, current_station, operation_date, wagon_number, operation_road)
    для ПОСЛЕДНЕЙ записи по любому контейнеру из поезда train_no.
    Если контейнеров нет — None.
    """
    async with SessionLocal() as session:
        q_ctn = (
            select(TerminalContainer.container_number)
            .where(TerminalContainer.train == train_no)
            .limit(1)
        )
        ctn = (await session.execute(q_ctn)).scalar()
        if not ctn:
            return None

        q_latest = (
            select(
                Tracking.container_number,
                Tracking.operation,
                Tracking.current_station,
                Tracking.operation_date,  # у тебя строка — выводим как есть
                Tracking.wagon_number,
                Tracking.operation_road,
            )
            .where(Tracking.container_number == ctn)
            .order_by(desc(Tracking.id))   # надёжно как "последняя вставка"
            .limit(1)
        )
        row = (await session.execute(q_latest)).first()
        return row if row else None