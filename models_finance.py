# models_finance.py
import enum
from datetime import date, datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    String, Integer, Float, Boolean, Date, DateTime, ForeignKey, 
    Enum as PgEnum, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db_base import Base

# Используем TYPE_CHECKING, чтобы избежать циклических импортов при проверке типов
if TYPE_CHECKING:
    from model.terminal_container import TerminalContainer

# --- Enums ---

class ServiceType(str, enum.Enum):
    TRAIN = "TRAIN"       # Контейнерный поезд
    SINGLE = "SINGLE"     # Повагонная отправка

class WagonType(str, enum.Enum):
    PLATFORM = "PLATFORM" # Фитинговая платформа
    GONDOLA = "GONDOLA"   # Полувагон

class CalculationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"

class MarginType(str, enum.Enum):
    FIX = "FIX"           # Фиксированная сумма
    PERCENT = "PERCENT"   # Процент

# --- Модели Справочников ---

class SystemSetting(Base):
    __tablename__ = "system_settings"
    
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class RailTariffRate(Base):
    __tablename__ = "rail_tariff_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    station_from_code: Mapped[str] = mapped_column(String(6), index=True)
    station_to_code: Mapped[str] = mapped_column(String(6), index=True)
    container_type: Mapped[str] = mapped_column(String(10))
    
    # ✅ НОВОЕ ПОЛЕ: Тип сервиса (TRAIN по умолчанию)
    # create_type=False важно, так как тип servicetype уже создан в таблице calculations
    service_type: Mapped[ServiceType] = mapped_column(
        PgEnum(ServiceType, name="servicetype", create_type=False), 
        default=ServiceType.TRAIN,
        nullable=False
    )
    
    rate_no_vat: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ✅ ОБНОВЛЕННАЯ УНИКАЛЬНОСТЬ: Теперь уникальна связка с учетом ТИПА СЕРВИСА
    __table_args__ = (
        UniqueConstraint(
            'station_from_code', 
            'station_to_code', 
            'container_type', 
            'service_type',  # <-- Добавили сюда
            name='uq_tariff_route_type_service' # <-- Новое имя ограничения
        ),
    )

# --- Модели Калькулятора ---

class Calculation(Base):
    __tablename__ = "calculations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, index=True)
    
    service_provider: Mapped[str] = mapped_column(String, index=True)
    service_type: Mapped[ServiceType] = mapped_column(PgEnum(ServiceType, name="servicetype"), default=ServiceType.TRAIN)
    wagon_type: Mapped[WagonType] = mapped_column(PgEnum(WagonType, name="wagontype"), default=WagonType.PLATFORM)
    container_type: Mapped[str] = mapped_column(String(10))
    
    station_from: Mapped[str] = mapped_column(String)
    station_to: Mapped[str] = mapped_column(String)
    
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    margin_type: Mapped[MarginType] = mapped_column(PgEnum(MarginType, name="margintype"), default=MarginType.FIX)
    margin_value: Mapped[float] = mapped_column(Float, default=0.0)
    total_price_netto: Mapped[float] = mapped_column(Float, default=0.0)
    vat_rate: Mapped[float] = mapped_column(Float, default=20.0)
    
    status: Mapped[CalculationStatus] = mapped_column(PgEnum(CalculationStatus, name="calculationstatus"), default=CalculationStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[List["CalculationItem"]] = relationship(back_populates="calculation", cascade="all, delete-orphan")

class CalculationItem(Base):
    __tablename__ = "calculation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    calculation_id: Mapped[int] = mapped_column(ForeignKey("calculations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    cost_price: Mapped[float] = mapped_column(Float)
    is_auto_calculated: Mapped[bool] = mapped_column(Boolean, default=False)

    calculation: Mapped["Calculation"] = relationship(back_populates="items")

# --- Модели Финансов Рейса ---

class ContainerFinance(Base):
    __tablename__ = "container_finances"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Ссылка на TerminalContainer (One-to-One)
    terminal_container_id: Mapped[int] = mapped_column(ForeignKey("terminal_containers.id", ondelete="CASCADE"), unique=True)
    
    source_calculation_id: Mapped[int | None] = mapped_column(ForeignKey("calculations.id", ondelete="SET NULL"))
    
    cost_value: Mapped[float] = mapped_column(Float, default=0.0)
    sales_price: Mapped[float] = mapped_column(Float, default=0.0)
    extra_expenses: Mapped[float] = mapped_column(Float, default=0.0)
    margin_abs: Mapped[float] = mapped_column(Float, default=0.0) # Для кэширования маржи

    # Связи (используем строковые имена для избежания циклических импортов)
    container: Mapped["TerminalContainer"] = relationship("TerminalContainer", back_populates="finance")
    calculation: Mapped["Calculation"] = relationship("Calculation")