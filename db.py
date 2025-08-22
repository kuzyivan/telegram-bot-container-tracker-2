# db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, delete, update
from config import DATABASE_URL

from models import Base, TrackingSubscription, Tracking, User, Stats  # ← Берём общий Base здесь
# НИКАКИХ импортов из model.terminal_container здесь!

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

# ---- вспомогательные функции ниже без импортов моделей сверху ----
async def get_all_user_ids():
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        return [row[0] for row in result.fetchall() if row[0] is not None]

async def get_tracked_containers_by_user(user_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription.containers).where(TrackingSubscription.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row if row else []

async def remove_user_tracking(user_id):
    async with SessionLocal() as session:
        await session.execute(
            delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id)
        )
        await session.commit()

async def set_user_email(telegram_id, username, email):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user:
            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(username=username, email=email, email_enabled=True)
            )
        else:
            new_user = User(
                telegram_id=telegram_id,
                username=username,
                email=email,
                email_enabled=True
            )
            session.add(new_user)

        await session.commit()