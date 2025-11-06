# queries/notification_queries.py

import logging
from sqlalchemy.future import select
from sqlalchemy.orm import aliased
from sqlalchemy import func, text
from db import async_sessionmaker # Импортируем фабрику
from models import Tracking, Subscription, User, UserEmail, SubscriptionEmail
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# =========================================================================
# === ИСПРАВЛЕННАЯ ФУНКЦИЯ (ДЛЯ ОШИБОК ИЗ ЛОГА) ===
# =========================================================================

async def get_tracking_data_for_containers(container_numbers: list[str]) -> list[Tracking]:
    """
    Получает ПОСЛЕДНЮЮ запись о дислокации для каждого 
    контейнера из списка.
    
    (Версия 3 - Исправлена ошибка 'function to_timestamp(timestamp... does not exist'
     и ошибка 'AttributeError: 'async_sessionmaker' object has no attribute 'execute'')
    """
    if not container_numbers:
        return []
        
    logger.info(f"[Queries] Поиск последних данных для {len(container_numbers)} контейнеров.")
    
    # --- ИСПРАВЛЕНИЕ: Мы ВЫЗЫВАЕМ "фабрику" (со скобками), чтобы получить сессию.
    session = async_sessionmaker() # <--- ИСПРАВЛЕНО (строка ~56)
    try:
        
        # --- ИСПРАВЛЕННЫЙ ЗАПРОС ---
        # Создаем подзапрос (Common Table Expression - CTE)
        subquery = select(
            Tracking,
            func.row_number().over(
                partition_by=Tracking.container_number,
                
                # --- ИСПРАВЛЕНИЕ ---
                # Раньше было: func.TO_TIMESTAMP(Tracking.operation_date, ...).desc()
                # Это вызывало ошибку, так как operation_date - УЖЕ TIMESTAMP.
                # Теперь мы сортируем напрямую по полю.
                order_by=Tracking.operation_date.desc()
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                
            ).label('rn')
        ).where(Tracking.container_number.in_(container_numbers)).subquery()

        # Создаем псевдоним (alias) для CTE
        t_aliased = aliased(Tracking, subquery)

        # Выбираем только те строки, где rn = 1 (т.е. самые последние)
        stmt = select(t_aliased).where(subquery.c.rn == 1)

        # Теперь .execute() вызывается у ЭКЗЕМПЛЯРА сессии
        result = await session.execute(stmt) # <--- ИСПРАВЛЕНО (строка ~58)
        return result.scalars().all()

    except Exception as e:
        logger.error(f"Ошибка в get_tracking_data_for_containers: {e}", exc_info=True)
        return []
    finally:
        # и .close() вызывается у ЭКЗЕМПЛЯРА сессии
        await session.close() # <--- ИСПРАВЛЕНО (строка ~66)


# =========================================================================
# === ОСТАЛЬНЫЕ ФУНКЦИИ (ЗДЕСЬ ТОЖЕ ИСПРАВЛЕНО) ===
# =========================================================================

async def get_subscriptions_for_notifications() -> List[Dict[str, Any]]:
    """
    Получает список всех активных подписок, 
    включая telegram_id пользователя и email'ы.
    """
    logger.info("[Queries] Запрос активных подписок для рассылки...")
    
    # --- ИСПРАВЛЕНИЕ: Вызываем фабрику ---
    session = async_sessionmaker() # <--- ИСПРАВЛЕНО (строка ~81)
    try:
        # Выбираем User.telegram_id, Subscription.id, Subscription.containers
        stmt_subscriptions = (
            select(
                User.telegram_id,
                Subscription.id.label("subscription_id"),
                Subscription.containers,
                Subscription.subscription_name
            )
            .join(User, User.telegram_id == Subscription.user_telegram_id)
            .where(Subscription.is_active == True)
        )
        
        result_subscriptions = await session.execute(stmt_subscriptions) # <--- ИСПРАВЛЕНО (строка ~95)
        subscriptions_data = result_subscriptions.mappings().all()

        if not subscriptions_data:
            logger.info("[Queries] Активных подписок не найдено.")
            return []

        # Выбираем email'ы для этих подписок
        subscription_ids = [sub["subscription_id"] for sub in subscriptions_data]
        
        stmt_emails = (
            select(
                SubscriptionEmail.subscription_id,
                UserEmail.email
            )
            .join(UserEmail, UserEmail.id == SubscriptionEmail.email_id)
            .where(SubscriptionEmail.subscription_id.in_(subscription_ids))
            .where(UserEmail.is_verified == True) # Только верифицированные email
        )
        
        result_emails = await session.execute(stmt_emails) # <--- ИСПРАВЛЕНО (строка ~115)
        
        # Группируем email'ы по subscription_id
        emails_map: Dict[int, List[str]] = {}
        for row in result_emails.mappings().all():
            sub_id = row["subscription_id"]
            if sub_id not in emails_map:
                emails_map[sub_id] = []
            emails_map[sub_id].append(row["email"])

        # Собираем финальный результат
        final_subscriptions: List[Dict[str, Any]] = []
        for sub in subscriptions_data:
            sub_id = sub["subscription_id"]
            final_subscriptions.append({
                "telegram_id": sub["telegram_id"],
                "subscription_name": sub["subscription_name"],
                "containers": sub["containers"],
                "emails": emails_map.get(sub_id, []) # Добавляем список email'ов
            })

        logger.info(f"[Queries] Найдено {len(final_subscriptions)} активных подписок для обработки.")
        return final_subscriptions

    except Exception as e:
        logger.error(f"Ошибка в get_subscriptions_for_notifications: {e}", exc_info=True)
        return []
    finally:
        # --- ИСПРАВЛЕНИЕ: Закрываем экземпляр ---
        await session.close() # <--- ИСПРАВЛЕНО (строка ~144)