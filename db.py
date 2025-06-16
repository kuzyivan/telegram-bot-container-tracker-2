from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select
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

from models import Stats

async def get_all_user_ids():
    """
    Возвращает список всех уникальных user_id из таблицы stats.
    Используется для рассылки.
    """
    async with SessionLocal() as session:
        result = await session.execute(select(Stats.user_id).distinct())
        user_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return user_ids
