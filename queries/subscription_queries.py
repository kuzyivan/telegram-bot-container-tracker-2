# queries/subscription_queries.py
"""
Запросы SQLAlchemy для управления подписками пользователей.
"""
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload

from db import SessionLocal
# ✅ Исправляем импорт здесь: TrackingSubscription -> Subscription
from models import Subscription, UserEmail, SubscriptionEmail 
from logger import get_logger

logger = get_logger(__name__)

async def get_user_subscriptions(telegram_id: int) -> list[Subscription]:
    """Получает все активные подписки пользователя."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.target_emails).selectinload(SubscriptionEmail.email)) # Загружаем emails
            .filter(Subscription.user_telegram_id == telegram_id, Subscription.is_active == True)
            .order_by(Subscription.subscription_name)
        )
        subscriptions = result.scalars().unique().all()
        return list(subscriptions)

async def delete_subscription(subscription_id: int, telegram_id: int) -> bool:
    """Удаляет подписку по ID, если она принадлежит пользователю."""
    async with SessionLocal() as session:
        async with session.begin():
            # Сначала найдем подписку, чтобы убедиться, что она принадлежит пользователю
            result = await session.execute(
                select(Subscription).filter(Subscription.id == subscription_id, Subscription.user_telegram_id == telegram_id)
            )
            subscription_to_delete = result.scalar_one_or_none()

            if subscription_to_delete:
                # Удаляем связанные записи в SubscriptionEmail (если cascade настроен, это не обязательно)
                await session.execute(
                    delete(SubscriptionEmail).where(SubscriptionEmail.subscription_id == subscription_id)
                )
                # Теперь удаляем саму подписку
                await session.delete(subscription_to_delete)
                # await session.execute(
                #     delete(Subscription).where(Subscription.id == subscription_id, Subscription.user_telegram_id == telegram_id)
                # )
                await session.commit()
                logger.info(f"Подписка ID {subscription_id} пользователя {telegram_id} успешно удалена.")
                return True
            else:
                logger.warning(f"Попытка удаления несуществующей или чужой подписки ID {subscription_id} пользователем {telegram_id}.")
                return False

async def get_subscription_details(subscription_id: int, telegram_id: int) -> Subscription | None:
    """Получает детали подписки по ID, если она принадлежит пользователю."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.target_emails).selectinload(SubscriptionEmail.email)) # Загружаем emails
            .filter(Subscription.id == subscription_id, Subscription.user_telegram_id == telegram_id)
        )
        subscription = result.scalar_one_or_none()
        return subscription

async def add_container_to_subscription(subscription_id: int, container_number: str, telegram_id: int) -> bool:
    """Добавляет контейнер к существующей подписке пользователя."""
    async with SessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(Subscription).filter(Subscription.id == subscription_id, Subscription.user_telegram_id == telegram_id)
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                if container_number not in subscription.containers:
                    # Используем func.array_append для добавления в массив PostgreSQL
                    subscription.containers = func.array_append(Subscription.containers, container_number)
                    # SQLAlchemy 2.0 может требовать явного указания изменения, если работаем не с объектом напрямую
                    # stmt = update(Subscription).\
                    #     where(Subscription.id == subscription_id).\
                    #     values(containers=func.array_append(Subscription.containers, container_number))
                    # await session.execute(stmt)
                    await session.commit() # Сохраняем изменение объекта
                    logger.info(f"Контейнер {container_number} добавлен к подписке ID {subscription_id}")
                    return True
                else:
                    logger.info(f"Контейнер {container_number} уже есть в подписке ID {subscription_id}")
                    return False # Уже существует
            else:
                 logger.warning(f"Подписка ID {subscription_id} не найдена для пользователя {telegram_id}")
                 return False # Подписка не найдена

async def remove_container_from_subscription(subscription_id: int, container_number: str, telegram_id: int) -> bool:
    """Удаляет контейнер из подписки пользователя."""
    async with SessionLocal() as session:
         async with session.begin():
            result = await session.execute(
                select(Subscription).filter(Subscription.id == subscription_id, Subscription.user_telegram_id == telegram_id)
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                if container_number in subscription.containers:
                    # Используем func.array_remove для удаления из массива PostgreSQL
                    subscription.containers = func.array_remove(Subscription.containers, container_number)
                    await session.commit()
                    logger.info(f"Контейнер {container_number} удален из подписки ID {subscription_id}")
                    return True
                else:
                     logger.info(f"Контейнер {container_number} не найден в подписке ID {subscription_id}")
                     return False # Не найден
            else:
                logger.warning(f"Подписка ID {subscription_id} не найдена для пользователя {telegram_id}")
                return False # Подписка не найдена