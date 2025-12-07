# db.py
"""
Настройка асинхронной сессии SQLAlchemy для работы с базой данных.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL, TARIFF_DATABASE_URL 
from db_base import Base 

# --- ИМПОРТ МОДЕЛЕЙ ---
# Важно импортировать ВСЕ модули, где определены классы моделей.
# Это нужно для того, чтобы:
# 1. Alembic/SQLAlchemy видели их в Base.metadata.
# 2. Работали связи (relationship) между таблицами (Registry).

# 1. Основные модели (из models.py)
from models import (
    Subscription, Tracking, User, UserEmail, SubscriptionEmail, UserRequest, 
    StationsCache, TrainEventLog, VerificationCode, Train, Company, CompanyContainer, 
    EventAlertRule, ScheduledTrain, ScheduleShareLink, TrackingHistory
)

# 2. Модель контейнера (вынесена в отдельный файл)
from model.terminal_container import TerminalContainer 

# 3. ✅ ФИНАНСОВЫЙ МОДУЛЬ (ОБЯЗАТЕЛЬНО)
# Импортируем, чтобы зарегистрировать классы ContainerFinance, Calculation и др.
import models_finance 

# --- НАСТРОЙКА ДВИЖКОВ ---

# Движок для основной БД (пользователи, подписки, поезда, финансы)
engine = create_async_engine(DATABASE_URL, echo=False) 

# Движок для БД тарифов (только чтение)
# Проверяем, что URL задан, иначе engine будет None
tariff_engine = None
if TARIFF_DATABASE_URL:
    tariff_engine = create_async_engine(TARIFF_DATABASE_URL, echo=False)
else:
    # Если URL не задан, бот выдаст ошибку при запуске
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: TARIFF_DATABASE_URL не найден в .env. Расчет тарифов может не работать.")

# --- ФАБРИКИ СЕССИЙ ---

# Сессия для основной БД
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

# --- УТИЛИТЫ ---

async def get_db() -> AsyncSession:
    """Dependency для FastAPI."""
    async with SessionLocal() as session:
        yield session

async def init_db():
    """
    Создает все таблицы, определенные через Base (только для ОСНОВНОЙ БД),
    если они еще не созданы.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)