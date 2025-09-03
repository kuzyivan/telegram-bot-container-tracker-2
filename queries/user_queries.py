# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import UserEmail
from logger import get_logger

logger = get_logger(__name__)

async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    """Возвращает список всех email-адресов для указанного пользователя."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserEmail)
            .where(UserEmail.user_telegram_id == telegram_id)
            .order_by(UserEmail.created_at)
        )
        return list(result.scalars().all())

async def add_user_email(telegram_id: int, email: str) -> Optional[UserEmail]:
    """Добавляет новый email для пользователя. 
    Возвращает объект UserEmail в случае успеха или None, если email уже существует."""
    
    # Проверка, не существует ли уже такой email у пользователя
    async with SessionLocal() as session:
        existing_email = await session.execute(
            select(UserEmail).where(UserEmail.user_telegram_id == telegram_id, UserEmail.email == email)
        )
        if existing_email.scalar_one_or_none():
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id}")
            return None

        new_email = UserEmail(user_telegram_id=telegram_id, email=email)
        session.add(new_email)
        try:
            await session.commit()
            await session.refresh(new_email)
            logger.info(f"Для пользователя {telegram_id} добавлен новый email: {email}")
            return new_email
        except IntegrityError: # На случай гонки запросов
            await session.rollback()
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id} (IntegrityError)")
            return None

async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    """Удаляет email по его ID, с проверкой, что он принадлежит указанному пользователю."""
    async with SessionLocal() as session:
        result = await session.execute(
            delete(UserEmail)
            .where(UserEmail.id == email_id, UserEmail.user_telegram_id == user_telegram_id)
        )
        await session.commit()
        # rowcount > 0 означает, что строка была найдена и удалена
        if result.rowcount > 0:
            logger.info(f"Email с ID {email_id} успешно удален для пользователя {user_telegram_id}")
            return True
        else:
            logger.warning(f"Не удалось удалить email с ID {email_id} для пользователя {user_telegram_id} (не найден или не принадлежит ему)")
            return False