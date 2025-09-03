# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from db import SessionLocal
from models import UserEmail
from logger import get_logger

logger = get_logger(__name__)

async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserEmail)
            .where(UserEmail.user_telegram_id == telegram_id)
            .order_by(UserEmail.created_at)
        )
        return list(result.scalars().all())

async def add_user_email(telegram_id: int, email: str) -> Optional[UserEmail]:
    async with SessionLocal() as session:
        existing_email = await session.execute(
            select(UserEmail).where(UserEmail.user_telegram_id == telegram_id, UserEmail.email == email)
        )
        if existing_email.scalar_one_or_none():
            logger.warning(f"Attempt to add existing email {email} for user {telegram_id}")
            return None
        new_email = UserEmail(user_telegram_id=telegram_id, email=email)
        session.add(new_email)
        try:
            await session.commit()
            await session.refresh(new_email)
            logger.info(f"New email added for user {telegram_id}: {email}")
            return new_email
        except IntegrityError:
            await session.rollback()
            logger.warning(f"Attempt to add existing email {email} for user {telegram_id} (IntegrityError)")
            return None

async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            delete(UserEmail)
            .where(UserEmail.id == email_id, UserEmail.user_telegram_id == user_telegram_id)
        )
        await session.commit()
        if result.rowcount > 0:
            logger.info(f"Email with ID {email_id} deleted for user {user_telegram_id}")
            return True
        else:
            logger.warning(f"Failed to delete email with ID {email_id} for user {user_telegram_id} (not found or not owner)")
            return False