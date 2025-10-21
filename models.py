# models.py
"""
Определяет основные ORM-модели SQLAlchemy для бота,
кроме TerminalContainer, которая находится в model/terminal_container.py.
"""
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String, Float, Integer, BigInteger, DateTime, Time, ARRAY, ForeignKey, Text, Boolean
)
from sqlalchemy.sql import func
from datetime import datetime, date, time

# Импортируем Base из нового файла
from db_base import Base

# --- Модели Пользователей и Связанные сущности ---
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True) # Добавляем первичный ключ id
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Связи
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    emails: Mapped[list["UserEmail"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    requests: Mapped[list["UserRequest"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class UserEmail(Base):
    __tablename__ = "user_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String, unique=True, index=True) # Email должен быть уникальным
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связь обратно к User
    user: Mapped["User"] = relationship(back_populates="emails")

class UserRequest(Base):
     __tablename__ = "user_requests"

     id: Mapped[int] = mapped_column(primary_key=True)
     user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
     query_text: Mapped[str] = mapped_column(Text)
     timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

     # Связь обратно к User
     user: Mapped["User"] = relationship(back_populates="requests")

# --- Модели Подписок ---
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    subscription_name: Mapped[str] = mapped_column(String, index=True)
    containers: Mapped[list[str]] = mapped_column(ARRAY(String))
    notification_time: Mapped[time] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связь обратно к User
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    # Связь к списку email адресов для рассылки по этой подписке
    target_emails: Mapped[list["SubscriptionEmail"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")

class SubscriptionEmail(Base):
    """Связывает подписку с email адресами пользователя для рассылки."""
    __tablename__ = "subscription_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    email_id: Mapped[int] = mapped_column(ForeignKey("user_emails.id", ondelete="CASCADE")) # Ссылка на конкретный email пользователя

    # Связи для удобного доступа
    subscription: Mapped["Subscription"] = relationship(back_populates="target_emails")
    email: Mapped["UserEmail"] = relationship() # Односторонняя связь к UserEmail


# --- Модели Слежения ---
class Tracking(Base):
    __tablename__ = "tracking"

    id: Mapped[int] = mapped_column(primary_key=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True)
    from_station: Mapped[str | None] = mapped_column(String)
    to_station: Mapped[str | None] = mapped_column(String)
    current_station: Mapped[str | None] = mapped_column(String)
    operation: Mapped[str | None] = mapped_column(String)
    operation_date: Mapped[str | None] = mapped_column(String) # Или DateTime, если формат всегда одинаков
    waybill: Mapped[str | None] = mapped_column(String)
    km_left: Mapped[int | None] = mapped_column(Integer)
    forecast_days: Mapped[float | None] = mapped_column(Float)
    wagon_number: Mapped[str | None] = mapped_column(String)
    operation_road: Mapped[str | None] = mapped_column(String)

# --- Модель Кеша Станций ---
class StationsCache(Base):
    __tablename__ = "stations_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    found_name: Mapped[str | None] = mapped_column(String, index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

# --- Модель Лога Событий Поездов ---
class TrainEventLog(Base):
    __tablename__ = "train_event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True)
    train_number: Mapped[str] = mapped_column(String, index=True)
    event_description: Mapped[str] = mapped_column(Text) # Описание события (прибыл/отправлен и т.д.)
    station: Mapped[str] = mapped_column(String) # Станция, где произошло событие
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True)) # Время события из отчета
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)) # Когда отправили уведомление

# ❌ Удален импорт TerminalContainer отсюда