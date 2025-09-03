# models.py

from sqlalchemy import (Boolean, Column, Integer, String, BigInteger, DateTime,
                        Time, ARRAY, ForeignKey, Table, Float) # <--- ИСПРАВЛЕНИЕ: Добавлен Float
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from logger import get_logger

logger = get_logger(__name__)
Base = declarative_base()

# --- НОВАЯ СВЯЗУЮЩАЯ ТАБЛИЦА ---
subscription_email_association = Table(
    "subscription_email_association",
    Base.metadata,
    Column("subscription_id", Integer, ForeignKey("tracking_subscriptions.id"), primary_key=True),
    Column("email_id", Integer, ForeignKey("user_emails.id"), primary_key=True),
)

# --- НОВАЯ ТАБЛИЦА ДЛЯ EMAIL-АДРЕСОВ ---
class UserEmail(Base):
    __tablename__ = "user_emails"
    
    id = Column(Integer, primary_key=True)
    user_telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    email = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="emails")
    
    subscriptions = relationship(
        "TrackingSubscription",
        secondary=subscription_email_association,
        back_populates="target_emails"
    )

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    
    subscriptions = relationship("TrackingSubscription", back_populates="user", cascade="all, delete-orphan")
    emails = relationship("UserEmail", back_populates="user", cascade="all, delete-orphan")

# --- ОБНОВЛЕННАЯ ТАБЛИЦА ПОДПИСОК ---
class TrackingSubscription(Base):
    __tablename__ = "tracking_subscriptions"
    
    id = Column(Integer, primary_key=True)
    display_id = Column(String, unique=True, nullable=False, index=True)
    user_telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    subscription_name = Column(String, nullable=False)
    containers = Column(ARRAY(String), nullable=False)
    notify_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="subscriptions")
    
    target_emails = relationship(
        "UserEmail",
        secondary=subscription_email_association,
        back_populates="subscriptions"
    )

# --- Существующие модели, которые остаются без изменений ---
class Stats(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True)
    container_number = Column(String)
    user_id = Column(BigInteger)
    username = Column(String)
    timestamp = Column(DateTime, default=func.now())

class Tracking(Base):
    __tablename__ = "tracking"
    id = Column(Integer, primary_key=True)
    container_number = Column(String)
    from_station = Column(String)
    to_station = Column(String)
    current_station = Column(String)
    operation = Column(String)
    operation_date = Column(String)
    waybill = Column(String)
    km_left = Column(Integer)
    forecast_days = Column(Float) # <-- Теперь эта строка корректна
    wagon_number = Column(String)
    operation_road = Column(String)

# ВАЖНО: Убедитесь, что модель TerminalContainer также импортируется корректно
from model.terminal_container import TerminalContainer

__all__ = [
    "Base", "User", "UserEmail", "TrackingSubscription", 
    "Stats", "Tracking", "TerminalContainer"
]