# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import UserEmail, User # <<< ИЗМЕНЕНИЕ: Импортируем модель User
from logger import get_logger

logger = get_logger(__name__)

# ... (функции get_user_emails, add_user_email, delete_user_email остаются без изменений) ...
async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserEmail)
            .where(UserEmail.user_telegram_id == telegram_id)
            .order_by(UserEmail.created_at)
        )
        return list(result.scalars().all())

async def add_user_email(telegram_id: int, email: str) -> Optional[UserEmail]:
    email_lower = email.strip().lower()
    async with SessionLocal() as session:
        existing_email_query = await session.execute(
            select(UserEmail).where(
                UserEmail.user_telegram_id == telegram_id, 
                func.lower(UserEmail.email) == email_lower
            )
        )
        if existing_email_query.scalar_one_or_none():
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id}")
            return None
        new_email = UserEmail(user_telegram_id=telegram_id, email=email_lower)
        session.add(new_email)
        try:
            await session.commit()
            await session.refresh(new_email)
            logger.info(f"Для пользователя {telegram_id} добавлен новый email: {email_lower}")
            return new_email
        except IntegrityError:
            await session.rollback()
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id} (IntegrityError)")
            return None

async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            delete(UserEmail)
            .where(UserEmail.id == email_id, UserEmail.user_telegram_id == user_telegram_id)
        )
        await session.commit()
        if result.rowcount > 0:
            logger.info(f"Email с ID {email_id} успешно удален для пользователя {user_telegram_id}")
            return True
        else:
            logger.warning(f"Не удалось удалить email с ID {email_id} для пользователя {user_telegram_id} (не найден или не принадлежит ему)")
            return False

# <<< НОВАЯ ФУНКЦИЯ
async def register_user(telegram_id: int, username: str | None):
    """
    Добавляет пользователя в таблицу users, если его там нет.
    Использует ON CONFLICT DO NOTHING для избежания ошибок при дубликатах.
    """
    async with SessionLocal() as session:
        stmt = pg_insert(User).values(
            telegram_id=telegram_id,
            username=username
        ).on_conflict_do_nothing(
            index_elements=['telegram_id']
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(f"Пользователь {telegram_id} ({username}) зарегистрирован или уже существует.")