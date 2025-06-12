from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Float, Time, ARRAY
from sqlalchemy.sql import func
# ИСПРАВЛЕНО: Base импортируется из db.py, а не определяется заново.
from db import Base

class TrackingSubscription(Base):
    __tablename__ = "tracking_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True) # Добавлен индекс для ускорения поиска
    username = Column(String)
    containers = Column(ARRAY(String), nullable=False)
    notify_time = Column(Time, nullable=False)

class Stats(Base):
    __tablename__ = 'stats'

    id = Column(Integer, primary_key=True)
    container_number = Column(String, index=True)
    user_id = Column(BigInteger, index=True)
    username = Column(String)
    timestamp = Column(DateTime(timezone=True), default=func.now()) # Явно указываем timezone

class Tracking(Base):
    __tablename__ = 'tracking'

    id = Column(Integer, primary_key=True)
    container_number = Column(String, unique=True, index=True) # Номер контейнера должен быть уникальным
    from_station = Column(String)
    to_station = Column(String)
    current_station = Column(String)
    operation = Column(String)
    # ИСПРАВЛЕНО: Тип данных изменен на DateTime для корректной сортировки и фильтрации
    operation_date = Column(DateTime(timezone=True))
    waybill = Column(String)
    km_left = Column(Integer)
    forecast_days = Column(Float)
    wagon_number = Column(String)
    operation_road = Column(String)

