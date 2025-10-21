# queries/notification_queries.py
"""
Запросы SQLAlchemy для получения данных, необходимых для отправки уведомлений.
"""
from datetime import time, datetime, timedelta
from sqlalchemy import select, func, text, desc
from sqlalchemy.orm import selectinload

from db import SessionLocal
# ✅ Исправляем импорт здесь: TrackingSubscription -> Subscription
from models import Subscription, Tracking, UserEmail, SubscriptionEmail 
from logger import get_logger

logger = get_logger(__name__)

async def get_subscriptions_for_time(target_time: time) -> list[Subscription]:
    """
    Получает все активные подписки, для которых пришло время уведомления.
    Включает связанные email адреса.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.target_emails).selectinload(SubscriptionEmail.email)) # Загружаем email
            .filter(Subscription.notification_time == target_time, Subscription.is_active == True)
        )
        subscriptions = result.scalars().unique().all()
        return list(subscriptions)

async def get_tracking_data_for_containers(container_numbers: list[str]) -> list[Tracking]:
    """
    Получает последние данные дислокации для заданного списка контейнеров.
    Использует оконную функцию для выбора самой свежей записи по дате операции.
    """
    if not container_numbers:
        return []

    async with SessionLocal() as session:
        # Подзапрос с использованием row_number() для нумерации записей по дате операции
        # в обратном порядке (самая свежая будет номер 1) для каждого контейнера.
        subquery = select(
            Tracking,
            func.row_number().over(
                partition_by=Tracking.container_number,
                order_by=text("TO_TIMESTAMP(operation_date, 'DD.MM.YYYY HH24:MI') DESC") # Преобразуем строку в timestamp для сортировки
                # Используйте func.to_timestamp, если ваша СУБД это поддерживает напрямую:
                # order_by=func.to_timestamp(Tracking.operation_date, 'DD.MM.YYYY HH24:MI').desc() 
            ).label('rn')
        ).where(Tracking.container_number.in_(container_numbers)).subquery()

        # Основной запрос, который выбирает только строки с rn = 1 (самые свежие)
        stmt = select(subquery.c).where(subquery.c.rn == 1)
        
        # Выполняем запрос
        result = await session.execute(stmt)
        
        # Получаем объекты Tracking из результата
        tracking_data = [
             Tracking(
                 id=row.id,
                 container_number=row.container_number,
                 from_station=row.from_station,
                 to_station=row.to_station,
                 current_station=row.current_station,
                 operation=row.operation,
                 operation_date=row.operation_date,
                 waybill=row.waybill,
                 km_left=row.km_left,
                 forecast_days=row.forecast_days,
                 wagon_number=row.wagon_number,
                 operation_road=row.operation_road
             ) for row in result.mappings() # Используем mappings() для доступа к полям по имени
        ]
        
        return tracking_data

async def get_first_container_in_train(train_code: str) -> str | None:
     """Находит номер первого попавшегося контейнера в указанном поезде."""
     async with SessionLocal() as session:
         result = await session.execute(
             select(Tracking.container_number)
             .where(Tracking.train == train_code) # Предполагая, что в Tracking есть поле train
             .limit(1)
         )
         container = result.scalar_one_or_none()
         return container