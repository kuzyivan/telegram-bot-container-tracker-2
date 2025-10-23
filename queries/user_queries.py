# queries/user_queries.py
from typing import List, Optional
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from telegram import User as TelegramUser # Импортируем тип User из telegram для аннотации
import random
import string
from datetime import datetime, timedelta
from sqlalchemy.orm import Mapped, mapped_column 
from sqlalchemy import BigInteger, String, DateTime, Integer, Boolean

from db import SessionLocal
from models import UserEmail, User, UserRequest, Base 
from logger import get_logger

logger = get_logger(__name__)

# --- МОДЕЛЬ ДЛЯ КОДА ПОДТВЕРЖДЕНИЯ (Предполагается, что она существует в models.py/была создана миграцией) ---
class VerificationCode(Base):
    __tablename__ = "email_verification_codes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String(6))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
# ----------------------------------------------------


async def get_user_emails(telegram_id: int) -> List[UserEmail]:
    """Получает все ПОДТВЕРЖДЕННЫЕ email адреса пользователя."""
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
    Проверяет, что у ТЕКУЩЕГО пользователя нет такого адреса.
    """
    email_lower = email.strip().lower()
    async with SessionLocal() as session:
        try:
            async with session.begin(): # Начало транзакции
                # 1. Проверка на дубликат email у этого пользователя (уже подтвержденного)
                existing_verified_email = await session.execute(
                    select(UserEmail).where(
                        UserEmail.user_telegram_id == telegram_id, 
                        func.lower(UserEmail.email) == email_lower,
                        UserEmail.is_verified == True
                    )
                )
                if existing_verified_email.scalar_one_or_none():
                    logger.warning(f"Попытка добавить существующий email {email} для пользователя {telegram_id} (уже подтвержден)")
                    return None # Email уже существует у этого пользователя и подтвержден
                    
                # 2. Удаляем старую неподтвержденную или неактуальную запись (чтобы избежать дубликатов неподтвержденных)
                await session.execute(
                    delete(UserEmail).where(
                        UserEmail.user_telegram_id == telegram_id,
                        func.lower(UserEmail.email) == email_lower,
                        UserEmail.is_verified == False
                    )
                )
                
                # 3. Создаем новую запись, is_verified=False
                new_email = UserEmail(user_telegram_id=telegram_id, email=email_lower, is_verified=False)
                session.add(new_email)
                await session.flush()
                await session.refresh(new_email)
                
                logger.info(f"Для пользователя {telegram_id} добавлен новый НЕПОДТВЕРЖДЕННЫЙ email: {email_lower}")
                return new_email
        
        # Строка 79 находится здесь, за пределами try блока. 
        # Если блок try не был закрыт, 'except' вызовет ошибку.
        except IntegrityError as e: 
            await session.rollback()
            logger.error(f"Ошибка целостности при добавлении email {email} для пользователя {telegram_id}: {e}")
            return None

async def generate_and_save_verification_code(telegram_id: int, email: str) -> str:
    """Генерирует и сохраняет код подтверждения, удаляя старые."""
    code = ''.join(random.choices(string.digits, k=6))
    # Устанавливаем часовой пояс для now() (если не установлен в env.py)
    now_aware = datetime.now(datetime.now().astimezone().tzinfo) 
    expires_at = now_aware + timedelta(minutes=10) # Код действует 10 минут
    
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

            # 2. Активируем email в таблице UserEmail
            # Ищем НЕПОДТВЕРЖДЕННУЮ запись
            email_to_activate_result = await session.execute(
                select(UserEmail).where(
                    UserEmail.user_telegram_id == telegram_id,
                    UserEmail.email == verified_email,
                    UserEmail.is_verified == False
                )
            )
            email_to_activate = email_to_activate_result.scalar_one_or_none()
            
            if email_to_activate:
                email_to_activate.is_verified = True
                
                # Удаляем все неподтвержденные дубликаты этого адреса (если они есть)
                await session.execute(
                    delete(UserEmail).where(
                        UserEmail.user_telegram_id == telegram_id,
                        UserEmail.email == verified_email,
                        UserEmail.is_verified == False
                    )
                )
            else:
                 logger.warning(f"Код верный, но не найдена неподтвержденная запись для {verified_email}")
                 
            # 3. Удаляем код подтверждения
            await session.delete(verification_entry)
            await session.commit()
            
            logger.info(f"Email {verified_email} успешно подтвержден для пользователя {telegram_id}.")
            return verified_email if email_to_activate else None


async def delete_user_email(email_id: int, user_telegram_id: int) -> bool:
    """Удаляет email пользователя по ID."""
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

# --- НОВАЯ ФУНКЦИЯ ДЛЯ ОЧИСТКИ ---
async def delete_unverified_email(telegram_id: int, email: str) -> None:
    """Удаляет неподтвержденную запись email из базы данных."""
    email_lower = email.strip().lower()
    async with SessionLocal() as session:
        await session.execute(
            delete(UserEmail).where(
                UserEmail.user_telegram_id == telegram_id,
                func.lower(UserEmail.email) == email_lower,
                UserEmail.is_verified == False
            )
        )
        await session.commit()
        logger.info(f"Удалена неподтвержденная запись email: {email} для пользователя {telegram_id}")
# ----------------------------------


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
    async with SessionLocal() as session:
        result = await session.execute(
            select(User.telegram_id)
        )
        user_ids = result.scalars().all()
        return list(user_ids)
