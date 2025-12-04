# models.py
"""
Определяет основные ORM-модели SQLAlchemy для бота.
"""
import enum
from typing import Optional, List
from datetime import datetime, date, time

from sqlalchemy import (
    String, Integer, BigInteger, DateTime, Time, ARRAY, 
    ForeignKey, Text, Boolean, Date, Float, Enum as PgEnum,
    Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

# Импортируем Base из общего файла
from db_base import Base

# --- 1. Enums (Перечисления) ---

class UserRole(str, enum.Enum):
    """Роли пользователей в системе."""
    ADMIN = "admin"       # Супер-админ
    OWNER = "owner"       # Владелец компании
    MANAGER = "manager"   # Сотрудник компании
    VIEWER = "viewer"     # Только просмотр

# --- 2. Модели ЛК (Компании) ---

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    inn: Mapped[str | None] = mapped_column(String, index=True)
    import_mapping_key: Mapped[str | None] = mapped_column(String, index=True) 
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[List["User"]] = relationship(back_populates="company")
    containers: Mapped[List["CompanyContainer"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company(id={self.id}, name='{self.name}')>"

class CompanyContainer(Base):
    __tablename__ = "company_containers"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    container_number: Mapped[str] = mapped_column(String(11), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    company: Mapped["Company"] = relationship(back_populates="containers")

    def __repr__(self) -> str:
        return f"<CompanyContainer(id={self.id}, container='{self.container_number}')>"

# --- 3. Пользователи ---

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    
    # Auth & RBAC
    email_login: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(PgEnum(UserRole), default=UserRole.VIEWER, nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    subscriptions: Mapped[List["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    emails: Mapped[List["UserEmail"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    requests: Mapped[List["UserRequest"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    company: Mapped[Optional["Company"]] = relationship(back_populates="users")

class UserEmail(Base):
    __tablename__ = "user_emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String, index=True) 
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False) 
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped["User"] = relationship(back_populates="emails")

class VerificationCode(Base):
    __tablename__ = "email_verification_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String(6))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class UserRequest(Base):
     __tablename__ = "user_requests"
     id: Mapped[int] = mapped_column(primary_key=True)
     user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
     query_text: Mapped[str] = mapped_column(Text)
     timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
     user: Mapped["User"] = relationship(back_populates="requests")

# --- 4. Подписки и Трекинг ---

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    subscription_name: Mapped[str] = mapped_column(String, index=True)
    containers: Mapped[list[str]] = mapped_column(ARRAY(String))
    notification_time: Mapped[time] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    target_emails: Mapped[List["SubscriptionEmail"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")

class SubscriptionEmail(Base):
    __tablename__ = "subscription_emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    email_id: Mapped[int] = mapped_column(ForeignKey("user_emails.id", ondelete="CASCADE"))
    subscription: Mapped["Subscription"] = relationship(back_populates="target_emails")
    email: Mapped["UserEmail"] = relationship()

class Tracking(Base):
    __tablename__ = "tracking"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True, nullable=False)
    trip_start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    trip_end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    from_state: Mapped[str | None] = mapped_column(String)
    from_road: Mapped[str | None] = mapped_column(String)
    from_station: Mapped[str | None] = mapped_column(String)
    to_country: Mapped[str | None] = mapped_column(String)
    to_road: Mapped[str | None] = mapped_column(String)
    to_station: Mapped[str | None] = mapped_column(String)
    sender_tgnl: Mapped[str | None] = mapped_column(String)
    sender_name_short: Mapped[str | None] = mapped_column(String)
    sender_okpo: Mapped[str | None] = mapped_column(String(10))
    sender_name: Mapped[str | None] = mapped_column(String)
    receiver_tgnl: Mapped[str | None] = mapped_column(String)
    receiver_name_short: Mapped[str | None] = mapped_column(String)
    receiver_okpo: Mapped[str | None] = mapped_column(String(10))
    receiver_name: Mapped[str | None] = mapped_column(String)
    container_type: Mapped[str | None] = mapped_column(String)
    cargo_name: Mapped[str | None] = mapped_column(String)
    cargo_gng_code: Mapped[str | None] = mapped_column(String(12))
    cargo_weight_kg: Mapped[int | None] = mapped_column(Integer)
    is_loaded_trip: Mapped[bool | None] = mapped_column(Boolean)
    current_station: Mapped[str | None] = mapped_column(String)
    operation: Mapped[str | None] = mapped_column(String)
    operation_road: Mapped[str | None] = mapped_column(String)
    operation_mnemonic: Mapped[str | None] = mapped_column(String(10))
    operation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    container_state: Mapped[str | None] = mapped_column(String)
    train_index_full: Mapped[str | None] = mapped_column(String)
    train_number: Mapped[str | None] = mapped_column(String, index=True)
    wagon_number: Mapped[str | None] = mapped_column(String, index=True)
    seals_count: Mapped[int | None] = mapped_column(Integer)
    accept_state: Mapped[str | None] = mapped_column(String)
    surrender_state: Mapped[str | None] = mapped_column(String)
    accept_road: Mapped[str | None] = mapped_column(String)
    surrender_road: Mapped[str | None] = mapped_column(String)
    delivery_deadline: Mapped[date | None] = mapped_column(Date)
    total_distance: Mapped[int | None] = mapped_column(Integer)
    distance_traveled: Mapped[int | None] = mapped_column(Integer)
    km_left: Mapped[int | None] = mapped_column(Integer)
    last_op_idle_time_str: Mapped[str | None] = mapped_column(String)
    last_op_idle_days: Mapped[float | None] = mapped_column(Float)
    waybill: Mapped[str | None] = mapped_column(String)
    dispatch_id: Mapped[str | None] = mapped_column(String)
    waybill_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    forecast_days: Mapped[float | None] = mapped_column(Float)

class StationsCache(Base):
    __tablename__ = "stations_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    found_name: Mapped[str | None] = mapped_column(String, index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

class TrainEventLog(Base):
    __tablename__ = "train_event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True)
    train_number: Mapped[str] = mapped_column(String, index=True)
    event_description: Mapped[str] = mapped_column(Text)
    station: Mapped[str] = mapped_column(String)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Train(Base):
    __tablename__ = "trains"
    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_train_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    container_count: Mapped[int | None] = mapped_column(Integer)
    destination_station: Mapped[str | None] = mapped_column(String, index=True)
    departure_date: Mapped[date | None] = mapped_column(Date)
    overload_station_name: Mapped[str | None] = mapped_column(String, nullable=True)
    overload_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rzd_train_number: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    last_known_station: Mapped[str | None] = mapped_column(String)
    last_known_road: Mapped[str | None] = mapped_column(String)
    last_operation: Mapped[str | None] = mapped_column(String)
    last_operation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    km_remaining: Mapped[int | None] = mapped_column(Integer)
    eta_days: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class EventAlertRule(Base):
    __tablename__ = "event_alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    recipient_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True)
    subscription_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=True)
    user: Mapped[Optional["User"]] = relationship(foreign_keys=[recipient_user_id])
    subscription: Mapped[Optional["Subscription"]] = relationship(foreign_keys=[subscription_id])

# --- 5. КАЛЕНДАРЬ ПОЕЗДОВ ---
class ScheduledTrain(Base):
    """
    Планирование отправки поездов (для календаря).
    """
    __tablename__ = "scheduled_trains"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    destination: Mapped[str] = mapped_column(String, nullable=False)
    stock_info: Mapped[str | None] = mapped_column(String)
    wagon_owner: Mapped[str | None] = mapped_column(String)
    comment: Mapped[str | None] = mapped_column(Text)
    
    # НОВОЕ ПОЛЕ: Цвет события (HEX код)
    color: Mapped[str] = mapped_column(String, default="#3b82f6", nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# --- 6. ССЫЛКИ ДЛЯ ПУБЛИЧНОГО ДОСТУПА (Новое) ---

class ScheduleShareLink(Base):
    """
    Ссылки для публичного доступа к графику.
    """
    __tablename__ = "schedule_share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False) # Уникальный код
    name: Mapped[str] = mapped_column(String, nullable=False) # Кому дали
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# --- 7. МОДЕЛИ ДЛЯ РАСЧЕТА ТАРИФОВ ---

class TariffStation(Base):
    '''
    Таблица для хранения данных из 2-РП.csv.
    '''
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True) 
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True) 
    railway: Mapped[str | None] = mapped_column(String)
    operations: Mapped[str | None] = mapped_column(String)
    # Используем list[str] как Map для данных ТП, см. migrator
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String)) 

    __table_args__ = (
        Index('ix_tariff_stations_name_code', 'name', 'code'),
    )

class TariffMatrix(Base):
    '''
    Таблица для хранения данных из 3-*.csv.
    '''
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )

class RailwaySection(Base):
    """
    Хранит последовательность станций участка (из Книги 1).
    Например: участок Москва - Бологое.
    stations_list хранит список словарей: [{'c': '...', 'n': '...'}, ...]
    """
    __tablename__ = 'railway_sections'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Коды узловых станций (начала и конца участка), если удастся их извлечь
    node_start_code: Mapped[str | None] = mapped_column(String(6), index=True)
    node_end_code: Mapped[str | None] = mapped_column(String(6), index=True)
    
    # Имя файла или дороги (для группировки)
    source_file: Mapped[str | None] = mapped_column(String)
    
    # Самое важное: упорядоченный список станций
    # Используем JSONB, так как это массив объектов, и по нему можно искать
    stations_list: Mapped[list[dict]] = mapped_column(JSONB) 

        # Индекс для быстрого поиска: содержит ли участок конкретную станцию

        __table_args__ = (

            Index('ix_stations_list_gin', 'stations_list', postgresql_using='gin'),

        )

    

    

    