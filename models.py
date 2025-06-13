from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Float, Time, ARRAY
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
from db import Base, engine
import sqlalchemy as sa

class TrackingSubscription(Base):
    __tablename__ = "tracking_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String, nullable=True)
    containers = Column(ARRAY(String), nullable=False)
    notify_time = Column(Time, nullable=False)

class Stats(Base):
    __tablename__ = 'stats'

    id = Column(Integer, primary_key=True)
    container_number = Column(String)
    user_id = Column(BigInteger)
    username = Column(String)
    timestamp = Column(DateTime, default=func.now())

class Tracking(Base):
    __tablename__ = 'tracking'

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_number = Column(String, index=True)
    from_station = Column(String)
    to_station = Column(String)
    current_station = Column(String)
    operation = Column(String)
    operation_date = Column(String) # Рекомендуется использовать DateTime для сортировки
    waybill = Column(String)
    km_left = Column(Integer)
    forecast_days = Column(Float)
    wagon_number = Column(String)
    operation_road = Column(String)

# --- НОВОЕ: Временная таблица для безопасной загрузки данных ---
class TrackingTemp(Base):
    __tablename__ = 'tracking_temp'

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_number = Column(String, index=True)
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

async def create_temp_table():
    """Ensures the temporary table exists."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[TrackingTemp.__table__])

