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

# Основная рабочая таблица
class Tracking(Base):
    __tablename__ = "tracking"

    id = Column(Integer, primary_key=True)
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
    updated_at = Column(String)
    # Добавь остальные нужные поля по проекту

# Временная таблица для массовой загрузки
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

# Вспомогательная функция для обновления временной таблицы
async def create_temp_table(engine: AsyncEngine):
    """
    Удаляет временную таблицу tracking_temp (с индексами) и создаёт заново.
    Вызывать перед загрузкой каждого нового файла!
    """
    async with engine.begin() as conn:
        await conn.execute(text('DROP TABLE IF EXISTS tracking_temp CASCADE;'))
        await conn.run_sync(Base.metadata.create_all, tables=[TrackingTemp.__table__])