from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import os

# Получаем строку подключения из .env
DATABASE_URL = os.getenv("DATABASE_URL")

# Асинхронный движок через asyncpg
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# Асинхронная фабрика сессий
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Базовый класс для моделей
Base = declarative_base()
