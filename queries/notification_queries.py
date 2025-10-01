# queries/notification_queries.py
from datetime import time
from typing import Sequence, List
from sqlalchemy import select, func
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

async def get_tracking_data_for_containers(container_numbers: List[str]) -> Sequence[Tracking]:
    """
    Для каждого номера контейнера из списка находит самую последнюю запись о его дислокации,
    используя один эффективный запрос к БД для решения проблемы N+1.
    """
    # Если список контейнеров пуст, ничего не делаем
    if not container_numbers:
        return []

    async with SessionLocal() as session:
        # Шаг 1: Создаём подзапрос (subquery).
        # Он найдёт максимальный (самый свежий) ID записи для каждого контейнера из списка.
        subq = (
            select(func.max(Tracking.id).label("max_id"))
            .where(Tracking.container_number.in_(container_numbers))
            .group_by(Tracking.container_number)
            .subquery()
        )

        # Шаг 2: Делаем основной запрос.
        # Он выбирает все данные из таблицы Tracking, но только для тех записей,
        # чьи ID попали в наш список максимальных ID из подзапроса.
        result = await session.execute(
            select(Tracking).where(Tracking.id.in_(select(subq.c.max_id)))
        )
        
        # Возвращаем список объектов Tracking
        return result.scalars().all()