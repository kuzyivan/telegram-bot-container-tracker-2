from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import os

# Подключение к базе — строка должна быть в формате для asyncpg
# Пример: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = os.getenv("DATABASE_URL")

# Создание асинхронного движка SQLAlchemy
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # True — если нужен подробный SQL-лог
    future=True
)

# Асинхронная фабрика сессий
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Базовый класс для моделей
Base = declarative_base()
