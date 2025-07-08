from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, delete, update
from config import DATABASE_URL

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL must be set and not None")

# --- SQLAlchemy engine/session setup ---
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

from models import TrackingSubscription, Tracking, User, Stats

# --- USERS ---
# Получить пользователя по telegram_id
async def get_user_by_telegram_id(telegram_id):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

# Привязать или обновить email пользователя (и email_enabled)

async def set_user_email(telegram_id, username, email, enable_email=True):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            await session.execute(
                update(User).where(User.telegram_id == telegram_id)
                .values(username=username, email=email, email_enabled=enable_email)
            )
        else:
            session.add(User(
                telegram_id=telegram_id,
                username=username,
                email=email,
                email_enabled=enable_email
            ))
        await session.commit()

# Отключить рассылку на e-mail (ставит флаг False, но e-mail не удаляет)
async def disable_user_email(telegram_id):
    async with SessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(email_enabled=False)
        )
        await session.commit()

# Получить список всех email, где рассылка включена
async def get_all_emails():
    async with SessionLocal() as session:
        result = await session.execute(
            select(User.email).where(User.email != None, User.email_enabled == True)
        )
        return [row[0] for row in result.fetchall() if row[0]]

# --- STATS ---
async def get_all_user_ids():
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        user_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return user_ids

# --- TRACKING ---
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

# Можно добавить другие методы по необходимости (например, статистика, логирование и т.д.)