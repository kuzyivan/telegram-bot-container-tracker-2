# db.py
"""
Настройка асинхронной сессии SQLAlchemy для работы с базой данных.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base # Этот импорт не нужен, так как Base импортируется из db_base

from config import DATABASE_URL
from db_base import Base 

# Импортируем ВСЕ МОДЕЛИ, чтобы Base.metadata.create_all их увидел.
from models import Subscription, Tracking, User, UserEmail, SubscriptionEmail, UserRequest, StationsCache, TrainEventLog 
from model.terminal_container import TerminalContainer 
# --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Импортируем модель кода для init_db ---
from queries.user_queries import VerificationCode 
# -------------------------------------------------------------------


engine = create_async_engine(DATABASE_URL, echo=False) 

SessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

async def init_db():
    """
    Создает все таблицы, определенные через Base.
    Это гарантирует, что даже если Alembic не был запущен, или пропустил какую-то таблицу, 
    ORM создаст ее при первом запуске бота.
    """
    async with engine.begin() as conn:
        # NOTE: Это синхронный вызов внутри асинхронного блока.
        # SQLAlchemy 2.0 handle this correctly with asyncpg.
        await conn.run_sync(Base.metadata.create_all) 
