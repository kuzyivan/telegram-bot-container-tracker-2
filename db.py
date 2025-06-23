from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select
from config import DATABASE_URL

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL must be set and not None")

engine = create_async_engine(
    DATABASE_URL,
    future=True,
    pool_recycle=300,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

from models import Stats, User  # Добавь User

async def get_all_user_ids():
    """
    Возвращает список всех уникальных user_id из таблицы stats.
    Используется для рассылки.
    """
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        user_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return user_ids

# --- ДОБАВЬ функции работы с User ---

async def set_user_email(telegram_id: int, username: str, email: str):
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            user.email = email
            user.email_enabled = True
            user.username = username or user.username
        else:
            user = User(
                telegram_id=telegram_id,
                username=username,
                email=email,
                email_enabled=True,
            )
            session.add(user)
        await session.commit()

async def disable_user_email(telegram_id: int):
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            user.email_enabled = False
            await session.commit()

async def get_user_email(telegram_id: int):
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user and user.email_enabled:
            return user.email
        return None