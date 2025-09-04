# queries/notification_queries.py
from datetime import time
from typing import Sequence, List
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.engine.row import Row

from db import SessionLocal
from models import TrackingSubscription, Tracking

async def get_subscriptions_for_time(target_time: time) -> Sequence[TrackingSubscription]:
    """
    Получает из базы все активные подписки для указанного времени,
    сразу подгружая связанные с ними объекты User и UserEmail для эффективности.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription)
            .where(
                TrackingSubscription.notify_time == target_time,
                TrackingSubscription.is_active == True
            )
            .options(
                selectinload(TrackingSubscription.user),
                selectinload(TrackingSubscription.target_emails)
            )
        )
        return result.scalars().all()

async def get_tracking_data_for_containers(container_numbers: List[str]) -> List[Row]:
    """
    Для каждого номера контейнера из списка находит самую последнюю запись о его дислокации.
    Возвращает список строк с данными о трекинге.
    """
    rows = []
    async with SessionLocal() as session:
        # Этот запрос можно оптимизировать, но для текущих нужд он подходит
        for container in container_numbers:
            res = await session.execute(
                select(
                    Tracking.container_number,
                    Tracking.from_station,
                    Tracking.to_station,
                    Tracking.current_station,
                    Tracking.operation,
                    Tracking.operation_date,
                    Tracking.waybill,
                    Tracking.km_left,
                    Tracking.forecast_days,
                    Tracking.wagon_number,
                    Tracking.operation_road
                )
                .filter(Tracking.container_number == container)
                .order_by(Tracking.operation_date.desc())
            )
            track = res.first()
            if track:
                rows.append(track)
    return rows