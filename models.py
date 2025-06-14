from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, BigInteger

Base = declarative_base()


class Tracking(Base):
    __tablename__ = 'tracking'

    id = Column(Integer, primary_key=True)
    container_number = Column(String, nullable=False, index=True)
    station = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    operation_date = Column(DateTime, nullable=False, index=True)
    arrival = Column(Boolean, default=False)

    def __repr__(self):
        return (
            f"<Tracking(container_number={self.container_number}, "
            f"station={self.station}, operation={self.operation}, "
            f"operation_date={self.operation_date}, arrival={self.arrival})>"
        )


class TrackingSubscription(Base):
    __tablename__ = 'tracking_subscriptions'

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)      # id пользователя Telegram
    container_number = Column(String, nullable=False, index=True) # Контейнер, который отслеживает пользователь
    created_at = Column(DateTime, nullable=False)                 # Дата/время подписки
    active = Column(Boolean, default=True)                        # Флаг активности подписки

    def __repr__(self):
        return (
            f"<TrackingSubscription(user_id={self.user_id}, "
            f"container_number={self.container_number}, active={self.active})>"
        )