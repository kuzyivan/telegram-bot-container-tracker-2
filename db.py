from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# from sqlalchemy.orm import declarative_base # Этот импорт не нужен, так как Base импортируется из db_base

from config import DATABASE_URL
from db_base import Base 

# Импортируем ВСЕ МОДЕЛИ, чтобы Base.metadata.create_all их увидел.
# ВАЖНО: Импортируем их здесь, а не внутри queries/user_queries.py
from models import Subscription, Tracking, User, UserEmail, SubscriptionEmail, UserRequest, StationsCache, TrainEventLog 
from model.terminal_container import TerminalContainer 
# --- КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Импортируем модель кода из queries ---
# Этот импорт необходим, чтобы Base.metadata "увидел" эту модель при вызове init_db().
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
        await conn.run_sync(Base.metadata.create_all)