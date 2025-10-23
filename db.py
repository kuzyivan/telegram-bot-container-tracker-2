# db.py
"""
Настройка асинхронной сессии SQLAlchemy для работы с базой данных.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# from sqlalchemy.orm import declarative_base # Этот импорт не нужен, так как Base импортируется из db_base

from config import DATABASE_URL
from db_base import Base 

# Импортируем ВСЕ МОДЕЛИ, чтобы Base.metadata.create_all их увидел.
# VerificationCode теперь импортируется ИЗ models, а не queries, что разрывает цикл.
from models import (
    Subscription, Tracking, User, UserEmail, SubscriptionEmail, UserRequest, 
    StationsCache, TrainEventLog, VerificationCode # VerificationCode теперь здесь
)
from model.terminal_container import TerminalContainer 


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
    Это гарантирует, что ORM увидит все модели и создаст/обновит их при запуске.
    """
    async with engine.begin() as conn:
        # NOTE: Это синхронный вызов внутри асинхронного блока.
        await conn.run_sync(Base.metadata.create_all) 
