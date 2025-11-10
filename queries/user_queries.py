# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from telegram import User as TelegramUser # Импортируем тип User из telegram для аннотации
import random
import string
from datetime import datetime, timedelta
from sqlalchemy.orm import Mapped, mapped_column 
from sqlalchemy import BigInteger, String, DateTime, Integer, Boolean
from models import UserEmail, User, UserRequest, VerificationCode # Import VerificationCode from models.py
from logger import get_logger

logger = get_logger(__name__)


async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    """Получает все ПОДТВЕРЖДЕННЫЕ email адреса пользователя."""
    # Получаем SessionLocal внутри функции, чтобы избежать циклического импорта
    from db import SessionLocal 
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserEmail)
            .where(UserEmail.user_telegram_id == telegram_id)
            .where(UserEmail.is_verified == True) 
            .order_by(UserEmail.created_at)
        )
        return list(result.scalars().all())

async def add_unverified_email(telegram_id: int, email: str) -> Optional[UserEmail]:
    """
    Сохраняет email как НЕПОДТВЕРЖДЕННЫЙ. 
    Если адрес уже существует как НЕПОДТВЕРЖДЕННЫЙ, использует его для повторной отправки кода.
    """
    email_lower = email.strip().lower()
    from db import SessionLocal
    async with SessionLocal() as session:
        async with session.begin():
            
            # 1. Проверяем наличие уже подтвержденного адреса или существующего неподтвержденного
            existing_email_query = await session.execute(
                select(UserEmail).where(
                    UserEmail.user_telegram_id == telegram_id, 
                    func.lower(UserEmail.email) == email_lower
                )
            )
            existing_email = existing_email_query.scalar_one_or_none()
            
            if existing_email:
                if existing_email.is_verified:
                    logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id} (уже подтвержден)")
                    return None # Адрес уже подтвержден, выходим.
                else:
                    # Это существующая неподтвержденная запись. Используем ее для повторной отправки кода.
                    logger.info(f"Для пользователя {telegram_id} найден существующий НЕПОДТВЕРЖДЕННЫЙ email: {email}. Повторная отправка кода.")
                    return existing_email 
                
            # 2. Если адрес не найден (ни подтвержденный, ни неподтвержденный) - создаем новый.
            new_email = UserEmail(user_telegram_id=telegram_id, email=email_lower, is_verified=False)
            session.add(new_email)
            await session.flush()
            await session.refresh(new_email)
            
            logger.info(f"Для пользователя {telegram_id} добавлен новый НЕПОДТВЕРЖДЕННЫЙ email: {email_lower}")
            return new_email


async def generate_and_save_verification_code(telegram_id: int, email: str) -> str:
    """Генерирует и сохраняет код подтверждения, удаляя старые."""
    code = ''.join(random.choices(string.digits, k=6))
    now_aware = datetime.now(datetime.now().astimezone().tzinfo) 
    expires_at = now_aware + timedelta(minutes=10) # Код действует 10 минут
    
    from db import SessionLocal
    async with SessionLocal() as session:
        async with session.begin():
            # Удаляем все старые коды для этого пользователя и email
            await session.execute(
                delete(VerificationCode).where(
                    VerificationCode.user_telegram_id == telegram_id,
                    VerificationCode.email == email
                )
            )
            
            new_code = VerificationCode(
                user_telegram_id=telegram_id,
                email=email,
                code=code,
                expires_at=expires_at
            )
            session.add(new_code)
            await session.commit()
            
    logger.info(f"Сгенерирован код {code} для {email} пользователя {telegram_id}")
    return code

async def verify_code_and_activate_email(telegram_id: int, code: str) -> Optional[str]:
    """Проверяет код, подтверждает email и возвращает адрес или None."""
    from db import SessionLocal
    async with SessionLocal() as session:
        async with session.begin():
            now_aware = datetime.now(datetime.now().astimezone().tzinfo)
            
            # 1. Ищем актуальный код
            result = await session.execute(
                select(VerificationCode)
                .where(
                    VerificationCode.user_telegram_id == telegram_id,
                    VerificationCode.code == code,
                    VerificationCode.expires_at > now_aware
                )
                .order_by(VerificationCode.expires_at.desc())
                .limit(1)
            )
            verification_entry = result.scalar_one_or_none()
            
            if not verification_entry:
                return None # Код недействителен или истек
                
            verified_email = verification_entry.email

            # 2. Активируем email в таблице UserEmail (используем UPDATE для надежности)
            # Мы ищем неподтвержденную запись и обновляем ее
            update_stmt = update(UserEmail).where(
                UserEmail.user_telegram_id == telegram_id,
                UserEmail.email == verified_email.strip().lower(), # <-- ИСПРАВЛЕНИЕ
                UserEmail.is_verified == False
            ).values(is_verified=True)
            
            update_result = await session.execute(update_stmt)
            
            if update_result.rowcount == 0:
                 logger.warning(f"Код верный, но не найдена НЕПОДТВЕРЖДЕННАЯ запись для обновления: {verified_email}")
                 email_activated = False
            else:
                 email_activated = True
                 
                 # 3. Удаляем все остальные неподтвержденные дубликаты (если они были)
                 # Это избыточная очистка, но безопасная.
                 await session.execute(
                     delete(UserEmail).where(
                         UserEmail.user_telegram_id == telegram_id,
                         UserEmail.email == verified_email,
                         UserEmail.is_verified == False
                     )
                 )
                 
            # 4. Удаляем код подтверждения
            await session.delete(verification_entry)
            await session.commit()
            
            if email_activated:
                logger.info(f"Email {verified_email} успешно подтвержден для пользователя {telegram_id}.")
                return verified_email
            else:
                return None # Если активация не удалась, возвращаем None


async def delete_unverified_email(telegram_id: int, email: str) -> None:
    """Удаляет неподтвержденную запись UserEmail и все связанные коды."""
    from db import SessionLocal
    async with SessionLocal() as session:
        async with session.begin():
            # Удаляем неподтвержденную запись
            await session.execute(
                delete(UserEmail).where(
                    UserEmail.user_telegram_id == telegram_id,
                    UserEmail.email == email,
                    UserEmail.is_verified == False
                )
            )
            # Удаляем все связанные коды
            await session.execute(
                delete(VerificationCode).where(
                    VerificationCode.user_telegram_id == telegram_id,
                    VerificationCode.email == email
                )
            )
            await session.commit()
            logger.info(f"Очищены неподтвержденные данные для {email} пользователя {telegram_id}")


async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    """Удаляет email пользователя по ID."""
    from db import SessionLocal
    async with SessionLocal() as session:
        async with session.begin(): 
            result = await session.execute(
                select(UserEmail).where(UserEmail.id == email_id, UserEmail.user_telegram_id == user_telegram_id)
            )
            email_to_delete = result.scalar_one_or_none()
            
            if email_to_delete:
                await session.delete(email_to_delete)
                await session.commit()
                logger.info(f"Email с ID {email_id} успешно удален для пользователя {user_telegram_id}")
                return True
            else:
                logger.warning(f"Не удалось удалить email ID {email_id} для {user_telegram_id} (не найден или не принадлежит ему)")
                return False


async def register_user_if_not_exists(user: TelegramUser):
    """
    Добавляет пользователя в таблицу users, если его там нет.
    Обновляет username/first_name/last_name, если пользователь уже есть.
    """
    telegram_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name
    
    from db import SessionLocal
    async with SessionLocal() as session:
        stmt = pg_insert(User).values(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        ).on_conflict_do_update( 
            index_elements=['telegram_id'], 
            set_=dict(
                username=username,
                first_name=first_name,
                last_name=last_name,
                updated_at=func.now() 
            )
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(f"Пользователь {telegram_id} ({username}) зарегистрирован или обновлен.")


async def add_user_request(telegram_id: int, query_text: str):
    """
    Логирует текстовый запрос пользователя в таблицу user_requests.
    """
    from db import SessionLocal
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

async def get_all_user_ids() -> List[int]:
    """Возвращает список всех ID пользователей (telegram_id)."""
    from db import SessionLocal
    async with SessionLocal() as session:
        result = await session.execute(
            select(User.telegram_id)
        )
        user_ids = result.scalars().all()
        return list(user_ids)
