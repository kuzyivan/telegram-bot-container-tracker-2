# queries/event_queries.py
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from db import SessionLocal
from models import EventAlertRule
from logger import get_logger
from typing import List

logger = get_logger(__name__)

# --- Константы для типов правил ---
# Мы будем реализовывать пока только этот
RULE_GLOBAL_EMAIL = "GLOBAL_EMAIL_UNLOAD" 
EVENT_TYPE_UNLOAD = "UNLOAD"
CHANNEL_EMAIL = "EMAIL"


async def get_global_email_rules() -> List[EventAlertRule]:
    """
    Получает список всех глобальных E-mail правил для выгрузки.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(EventAlertRule)
            .where(
                EventAlertRule.event_type == EVENT_TYPE_UNLOAD,
                EventAlertRule.channel == CHANNEL_EMAIL,
                EventAlertRule.subscription_id == None # Глобальное правило
            )
            .order_by(EventAlertRule.recipient_email)
        )
        return list(result.scalars().all())

async def add_global_email_rule(email: str) -> bool:
    """
    Добавляет новое правило для E-mail, если его еще нет.
    """
    email_lower = email.strip().lower()
    rule_name = f"Global Unload Notification for {email_lower}"
    
    async with SessionLocal() as session:
        try:
            # --- ✅ ИСПРАВЛЕНИЕ: СНАЧАЛА ПРОВЕРЯЕМ ---
            # Проверим, нет ли уже такого email с такими же настройками
            existing = await session.execute(
                select(EventAlertRule).where(
                    EventAlertRule.recipient_email == email_lower,
                    EventAlertRule.event_type == EVENT_TYPE_UNLOAD,
                    EventAlertRule.channel == CHANNEL_EMAIL,
                    EventAlertRule.subscription_id == None # Убедимся, что это глобальное правило
                )
            )
            if existing.scalar_one_or_none():
                logger.warning(f"Правило для {email_lower} уже существует.")
                return False # Уже существует
            
            # --- ✅ ИСПРАВЛЕНИЕ: ТЕПЕРЬ ПРОСТО ВСТАВЛЯЕМ ---
            # Мы убрали on_conflict_do_nothing, так как он требовал
            # уникального индекса, которого у нас нет.
            # Ручной проверки (select) выше - достаточно.
            new_rule = EventAlertRule(
                rule_name=rule_name,
                event_type=EVENT_TYPE_UNLOAD,
                channel=CHANNEL_EMAIL,
                recipient_email=email_lower,
                subscription_id=None,
                recipient_user_id=None
            )
            session.add(new_rule)
            
            await session.commit()
            logger.info(f"Добавлено новое правило уведомления для {email_lower}")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при добавлении правила для {email_lower}: {e}", exc_info=True)
            return False

async def delete_event_rule_by_id(rule_id: int) -> bool:
    """
    Удаляет правило по его ID.
    """
    async with SessionLocal() as session:
        try:
            result = await session.execute(
                select(EventAlertRule).where(EventAlertRule.id == rule_id)
            )
            rule_to_delete = result.scalar_one_or_none()
            
            if rule_to_delete:
                await session.delete(rule_to_delete)
                await session.commit()
                logger.info(f"Удалено правило ID {rule_id} ({rule_to_delete.recipient_email})")
                return True
            else:
                logger.warning(f"Не найдено правило ID {rule_id} для удаления.")
                return False
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при удалении правила ID {rule_id}: {e}", exc_info=True)
            return False