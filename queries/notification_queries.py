# queries/notification_queries.py
from datetime import time
# ИСПРАВЛЕНИЕ 1: Импортируем 'Optional' для совместимости со старыми версиями Python
from typing import Sequence, List, Optional

from sqlalchemy import select, select as sync_select
from sqlalchemy.engine.row import Row

from db import SessionLocal
from models import TrackingSubscription, Tracking, User

async def get_subscriptions_for_time(target_time: time) -> Sequence[TrackingSubscription]:
    """
    Получает из базы данных все активные подписки для указанного времени уведомления.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        return result.scalars().all()

async def get_tracking_data_for_containers(container_numbers: List[str]) -> List[Row]:
    """
    Для каждого номера контейнера из списка находит самую последнюю запись о его дислокации.
    Возвращает список строк с данными о трекинге.
    """
    rows = []
    async with SessionLocal() as session:
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

# ИСПРАВЛЕНИЕ 2: Заменяем 'User | None' на 'Optional[User]'
async def get_user_for_email(user_telegram_id: int) -> Optional[User]:
    """
    Находит пользователя по его Telegram ID и проверяет, включены ли у него email-уведомления.
    Возвращает объект пользователя или None.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            sync_select(User).where(User.telegram_id == user_telegram_id, User.email_enabled == True)
        )
        return result.scalar_one_or_none()