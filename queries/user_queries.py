# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from telegram import User as TelegramUser # Импортируем тип User из telegram для аннотации

from db import SessionLocal
# ✅ Добавляем UserRequest
from models import UserEmail, User, UserRequest 
from logger import get_logger

logger = get_logger(__name__)

async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    """Получает все email адреса пользователя."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserEmail)
            .where(UserEmail.user_telegram_id == telegram_id)
            .order_by(UserEmail.created_at)
        )
        return list(result.scalars().all())

async def add_user_email(telegram_id: int, email: str) -> Optional[UserEmail]:
    """Добавляет новый email пользователю, если такого еще нет."""
    email_lower = email.strip().lower()
    async with SessionLocal() as session:
        # Проверка на дубликат email у этого пользователя
        existing_email_query = await session.execute(
            select(UserEmail).where(
                UserEmail.user_telegram_id == telegram_id, 
                func.lower(UserEmail.email) == email_lower
            )
        )
        if existing_email_query.scalar_one_or_none():
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id}")
            return None # Email уже существует у этого пользователя
            
        # Проверка на существование email у ДРУГОГО пользователя (если email должны быть уникальны глобально)
        # global_existing_email = await session.execute(
        #     select(UserEmail).where(func.lower(UserEmail.email) == email_lower)
        # )
        # if global_existing_email.scalar_one_or_none():
        #      logger.warning(f"Email {email} уже используется другим пользователем.")
        #      # Здесь можно вернуть ошибку или специальное значение
        #      return None # Email занят

        new_email = UserEmail(user_telegram_id=telegram_id, email=email_lower)
        session.add(new_email)
        try:
            await session.commit()
            await session.refresh(new_email)
            logger.info(f"Для пользователя {telegram_id} добавлен новый email: {email_lower}")
            return new_email
        except IntegrityError: # На случай, если гонка потоков или email все же должен быть глобально уникальным
            await session.rollback()
            logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id} (IntegrityError)")
            return None

async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    """Удаляет email пользователя по ID."""
    async with SessionLocal() as session:
        async with session.begin(): # Используем транзакцию
             # Сначала найдем email, чтобы убедиться, что он принадлежит пользователю
            result = await session.execute(
                select(UserEmail).where(UserEmail.id == email_id, UserEmail.user_telegram_id == user_telegram_id)
            )
            email_to_delete = result.scalar_one_or_none()
            
            if email_to_delete:
                # TODO: Нужно проверить, используется ли этот email в каких-либо подписках (SubscriptionEmail)
                # и либо запретить удаление, либо отвязать его от подписок.
                # Пока что просто удаляем.
                await session.delete(email_to_delete)
                await session.commit()
                logger.info(f"Email с ID {email_id} успешно удален для пользователя {user_telegram_id}")
                return True
            else:
                logger.warning(f"Не удалось удалить email ID {email_id} для {user_telegram_id} (не найден или не принадлежит ему)")
                return False


# ✅ Переименовываем функцию для единообразия с вызовами
async def register_user_if_not_exists(user: TelegramUser):
    """
    Добавляет пользователя в таблицу users, если его там нет.
    Обновляет username/first_name/last_name, если пользователь уже есть.
    """
    telegram_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name
    
    async with SessionLocal() as session:
        # Пытаемся вставить нового пользователя
        stmt = pg_insert(User).values(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        ).on_conflict_do_update( # Если пользователь с таким telegram_id уже существует...
            index_elements=['telegram_id'], # ...по ключу telegram_id...
            # ...обновляем его данные
            set_=dict(
                username=username,
                first_name=first_name,
                last_name=last_name,
                updated_at=func.now() # Обновляем время последнего визита/обновления
            )
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(f"Пользователь {telegram_id} ({username}) зарегистрирован или обновлен.")


# ✅ Добавляем недостающую функцию
async def add_user_request(telegram_id: int, query_text: str):
    """
    Логирует текстовый запрос пользователя в таблицу user_requests.
    """
    async with SessionLocal() as session:
        new_request = UserRequest(
            user_telegram_id=telegram_id,
            query_text=query_text
        )
        session.add(new_request)
        try:
            await session.commit()
            logger.debug(f"Запрос от {telegram_id} ('{query_text[:50]}...') залогирован.")
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка логирования запроса от {telegram_id}: {e}", exc_info=True)