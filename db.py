# db.py
"""
Настройка асинхронной сессии SQLAlchemy для работы с базой данных.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from config import DATABASE_URL
from db_base import Base 

# Импортируем только те модели, которые могут понадобиться ДЛЯ ИНИЦИАЛИЗАЦИИ
# или если другие модули импортируют их ИЗ ЭТОГО ФАЙЛА (что не рекомендуется).
# Для Alembic все модели импортируются в env.py.
# Оставляем только те, что могут быть нужны напрямую (например, если есть функции в этом файле)
from models import Subscription, Tracking, User # Пример - оставь, если нужны
from model.terminal_container import TerminalContainer # Пример

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)