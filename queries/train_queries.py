from __future__ import annotations
from sqlalchemy import select, func, desc, literal
from typing import List, Tuple, Optional

from db import SessionLocal
from models import TerminalContainer, Tracking

# ===== Сводка по клиентам =====
async def get_train_summary(train_no: str) -> List[Tuple[str, int]]:
    async with SessionLocal() as session:
        client_expr = func.coalesce(
            TerminalContainer.short_name,
            TerminalContainer.client,
            literal("Без клиента")
        )

        q = (
            select(
                client_expr.label("client_name"),
                func.count(func.distinct(TerminalContainer.container_number)).label("cnt")
            )
            .where(TerminalContainer.train == train_no)
            .group_by(client_expr)
            .order_by(desc("cnt"))
        )
        rows = (await session.execute(q)).all()
        return [(r.client_name, int(r.cnt)) for r in rows]

# ===== Любой контейнер + его последняя операция =====
async def get_train_latest_status(train_no: str) -> Optional[Tuple]:
    async with SessionLocal() as session:
        # берём любой контейнер из поезда
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
                Tracking.operation_date,
                Tracking.wagon_number,
                Tracking.operation_road,
            )
            .where(Tracking.container_number == ctn)
            .order_by(desc(Tracking.id))
            .limit(1)
        )
        return (await session.execute(q_latest)).first()