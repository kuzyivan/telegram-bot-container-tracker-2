# db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import DATABASE_URL

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL must be set and not None")

engine = create_async_engine(
    DATABASE_URL,
    future=True,
    pool_recycle=300,    # обновлять соединения каждые 5 минут
    pool_pre_ping=True,  # проверять соединение перед использованием
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()