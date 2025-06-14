from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Основная временная таблица для обработки выгрузок
class TrackingTemp(Base):
    __tablename__ = "tracking_temp"

    id = Column(Integer, primary_key=True)
    container_number = Column(String)
    from_station = Column(String)
    to_station = Column(String)
    current_station = Column(String)
    operation = Column(String)
    operation_date = Column(String)
    waybill = Column(String)
    km_left = Column(Integer)
    forecast_days = Column(Float)
    wagon_number = Column(String)
    operation_road = Column(String)

# Пример основной постоянной таблицы (если нужно, дополни своими)
class Container(Base):
    __tablename__ = "containers"

    id = Column(Integer, primary_key=True)
    container_number = Column(String, unique=True, index=True)
    owner = Column(String)
    status = Column(String)
    updated_at = Column(String)
    # ... добавь нужные поля

# Пример таблицы пользователей (если нужно)
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True)
    username = Column(String)
    is_admin = Column(Integer)  # 0 или 1

# ----------------- #
# ВСПОМОГАТЕЛЬНЫЕ   #
# ----------------- #

async def create_temp_table(engine: AsyncEngine):
    """
    Удаляет временную таблицу tracking_temp (с индексами) и создаёт заново.
    Вызывать перед загрузкой каждого нового файла!
    """
    async with engine.begin() as conn:
        await conn.execute(text('DROP TABLE IF EXISTS tracking_temp CASCADE;'))
        await conn.run_sync(Base.metadata.create_all, tables=[TrackingTemp.__table__])