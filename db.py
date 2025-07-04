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
    pool_pre_ping=True,  # Пинговать соединение при каждом использовании
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

from models import TrackingSubscription, Tracking, User, Stats

# Получить пользователя по telegram_id (используется для проверки email, и проч.)
async def get_user_by_telegram_id(telegram_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

# Получить все уникальные user_id для рассылки (статистика, возможно пригодится)
async def get_all_user_ids():
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        user_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return user_ids

# Получить все отслеживаемые контейнеры пользователя
async def get_tracked_containers_by_user(user_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription.containers).where(TrackingSubscription.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row if row else []

# Удалить все подписки пользователя (отписка от всех контейнеров)
async def remove_user_tracking(user_id):
    async with SessionLocal() as session:
        await session.execute(
            delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id)
        )
        await session.commit()

# Привязать или обновить email пользователя
async def set_user_email(telegram_id, username, email):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            await session.execute(
                update(User).where(User.telegram_id == telegram_id)
                .values(username=username, email=email)
            )
        else:
            session.add(User(telegram_id=telegram_id, username=username, email=email))
        await session.commit()

# Создать новую подписку на отслеживание с указанием канала доставки
async def create_tracking_subscription(user_id, username, containers, notify_time, delivery_channel):
    async with SessionLocal() as session:
        subscription = TrackingSubscription(
            user_id=user_id,
            username=username,
            containers=containers,
            notify_time=notify_time,
            delivery_channel=delivery_channel,
        )
        session.add(subscription)
        await session.commit()

# Получить все подписки пользователя (для админских нужд, опционально)
async def get_subscriptions_by_user(user_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.user_id == user_id)
        )
        return result.scalars().all()

# Получить список всех email подписчиков (например, для массовой email-рассылки)
async def get_all_emails():
    async with SessionLocal() as session:
        result = await session.execute(
            select(User.email).where(User.email != None)
        )
        return [row[0] for row in result.fetchall() if row[0]]

# Можно добавить другие методы по необходимости (например, статистика, логирование и т.д.)