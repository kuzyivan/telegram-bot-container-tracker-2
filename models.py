from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Float, Time, ARRAY
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from logger import get_logger

logger = get_logger(__name__)

try:
    Base = declarative_base()

    class TrackingSubscription(Base):
        __tablename__ = "tracking_subscriptions"

        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, nullable=False)
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

    logger.info("Модели БД успешно определены и готовы к использованию.")

except Exception as e:
    logger.critical(f"❌ Ошибка при инициализации моделей: {e}", exc_info=True)
