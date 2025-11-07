# db.py
"""
Настройка асинхронной сессии SQLAlchemy для работы с базой данных.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# --- 1. Импортируем TARIFF_DATABASE_URL ---
from config import DATABASE_URL, TARIFF_DATABASE_URL 
from db_base import Base 

# Импортируем ВСЕ МОДЕЛИ, чтобы Base.metadata.create_all их увидел.
from models import (
    Subscription, Tracking, User, UserEmail, SubscriptionEmail, UserRequest, 
    StationsCache, TrainEventLog, VerificationCode
)
from model.terminal_container import TerminalContainer 

# --- 2. Создаем ДВА движка ---
# Движок для основной БД (пользователи, подписки)
engine = create_async_engine(DATABASE_URL, echo=False) 

# Движок для БД тарифов (только чтение)
# Проверяем, что URL задан, иначе engine будет None
tariff_engine = None
if TARIFF_DATABASE_URL:
    tariff_engine = create_async_engine(TARIFF_DATABASE_URL, echo=False)
else:
    # Если URL не задан, бот выдаст ошибку при запуске
    print("КРИТИЧЕСКАЯ ОШИБКА: TARIFF_DATABASE_URL не найден в .env")
# --- 

# --- 3. Создаем ДВЕ фабрики сессий ---
SessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# Сессия для тарифов (если движок создан)
TariffSessionLocal = None
if tariff_engine:
    TariffSessionLocal = async_sessionmaker(
        bind=tariff_engine, 
        class_=AsyncSession, 
        expire_on_commit=False
    )
# ---

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

async def init_db():
    """
    Создает все таблицы, определенные через Base (только для ОСНОВНОЙ БД).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)