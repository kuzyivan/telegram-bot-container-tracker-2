# queries/subscription_queries.py
from typing import List, Optional
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload

from db import SessionLocal
from models import TrackingSubscription, UserEmail
from logger import get_logger

logger = get_logger(__name__)

async def get_user_subscriptions(telegram_id: int) -> List[TrackingSubscription]:
    """Возвращает список всех подписок для указанного пользователя."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription)
            .where(TrackingSubscription.user_telegram_id == telegram_id)
            .options(selectinload(TrackingSubscription.target_emails)) # Эффективно подгружаем связанные email
            .order_by(TrackingSubscription.created_at)
        )
        return list(result.scalars().all())

async def get_subscription_details(subscription_id: int, user_telegram_id: int) -> Optional[TrackingSubscription]:
    """Возвращает детали конкретной подписки с проверкой владения."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription)
            .where(TrackingSubscription.id == subscription_id, TrackingSubscription.user_telegram_id == user_telegram_id)
            .options(selectinload(TrackingSubscription.target_emails))
        )
        return result.scalar_one_or_none()

async def create_subscription(
    user_id: int, 
    name: str, 
    containers: List[str], 
    notify_time, 
    email_ids: List[int]
) -> TrackingSubscription:
    """Создает новую подписку и связывает ее с выбранными email."""
    async with SessionLocal() as session:
        # 1. Получаем количество существующих подписок для генерации ID
        count_result = await session.execute(
            select(func.count(TrackingSubscription.id)).where(TrackingSubscription.user_telegram_id == user_id)
        )
        sub_count = count_result.scalar_one()
        display_id = f"SUB-{user_id}-{sub_count + 1}"

        # 2. Находим объекты email по их ID
        target_emails = []
        if email_ids:
            email_result = await session.execute(
                select(UserEmail).where(UserEmail.id.in_(email_ids), UserEmail.user_telegram_id == user_id)
            )
            target_emails = list(email_result.scalars().all())

        # 3. Создаем новую подписку
        new_sub = TrackingSubscription(
            display_id=display_id,
            user_telegram_id=user_id,
            subscription_name=name,
            containers=containers,
            notify_time=notify_time,
            target_emails=target_emails # SQLAlchemy автоматически обработает связь many-to-many
        )
        session.add(new_sub)
        await session.commit()
        logger.info(f"Создана новая подписка '{name}' ({display_id}) для пользователя {user_id}")
        return new_sub

async def delete_subscription(subscription_id: int, user_telegram_id: int) -> bool:
    """Удаляет подписку по ее ID с проверкой владения."""
    async with SessionLocal() as session:
        sub_to_delete = await session.get(TrackingSubscription, subscription_id)
        
        # 1. Проверяем, существует ли подписка вообще
        if not sub_to_delete:
            logger.warning(f"Попытка удаления несуществующей подписки ID {subscription_id} пользователем {user_telegram_id}")
            return False
            
        # 2. Проверяем, принадлежит ли она этому пользователю
        if sub_to_delete.user_telegram_id != user_telegram_id:
            logger.warning(f"Попытка удаления чужой подписки ID {subscription_id} пользователем {user_telegram_id}")
            return False

        # Если все проверки пройдены, удаляем
        await session.delete(sub_to_delete)
        await session.commit()
        logger.info(f"Подписка ID {subscription_id} успешно удалена для пользователя {user_telegram_id}")
        return True