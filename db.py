from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, delete, update
from config import DATABASE_URL

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL must be set and not None")

engine = create_async_engine(
    DATABASE_URL,
    future=True,
    pool_recycle=300,    # Обновлять соединения каждые 5 минут
    pool_pre_ping=True,  # Перед каждым использованием — пингуем
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

from models import Stats, TrackingSubscription, Users

async def get_all_user_ids():
    """
    Возвращает список всех уникальных user_id из таблицы stats.
    Используется для рассылки.
    """
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        user_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return user_ids

# ====== Добавлено для handlers/user_handlers ======

async def get_tracked_containers_by_user(user_id):
    """
    Получить все отслеживаемые контейнеры пользователя.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscriptions.containers).where(TrackingSubscriptions.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row if row else []

async def remove_user_tracking(user_id):
    """
    Удалить все подписки пользователя (отписка от всех контейнеров).
    """
    async with SessionLocal() as session:
        await session.execute(
            delete(TrackingSubscriptions).where(TrackingSubscriptions.user_id == user_id)
        )
        await session.commit()

async def set_user_email(telegram_id, username, email):
    """
    Привязать или обновить email пользователя.
    Если пользователь существует — обновить. Иначе — создать.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(Users).where(Users.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            await session.execute(
                update(Users).where(Users.telegram_id == telegram_id)
                .values(username=username, email=email)
            )
        else:
            session.add(Users(telegram_id=telegram_id, username=username, email=email))
        await session.commit()