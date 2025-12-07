# model/terminal_container.py
"""
Определяет ORM-модель SQLAlchemy для контейнеров на терминале.
"""
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Time, Date, Float
from sqlalchemy.sql import func
from datetime import datetime, date, time

# Импортируем Base из общего файла
from db_base import Base

if TYPE_CHECKING:
    # Импортируем только для подсказок типов (Type Hinting), 
    # чтобы избежать ошибки Runtime (Circular Import) при запуске.
    from models_finance import ContainerFinance

class TerminalContainer(Base):
    """Модель для хранения информации о контейнерах на терминале."""
    __tablename__ = 'terminal_containers'

    id: Mapped[int] = mapped_column(primary_key=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True, unique=True)
    client: Mapped[str | None] = mapped_column(String)
    
    accept_date: Mapped[date | None] = mapped_column(Date) 
    accept_time: Mapped[time | None] = mapped_column(Time)
    train: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str | None] = mapped_column(String) # Например: 'ПРИНЯТ', 'ОТГРУЖЕН'
    
    # --- Новые поля для Калькулятора ---
    weight_brutto: Mapped[float | None] = mapped_column(Float)
    weight_netto: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        onupdate=func.now(), 
        server_default=func.now()
    )
    
    # --- Связи ---
    # Связь с финансовым профилем (One-to-One).
    # uselist=False гарантирует, что у одного контейнера одна запись финансов.
    finance: Mapped["ContainerFinance"] = relationship(
        "ContainerFinance", 
        back_populates="container", 
        uselist=False, 
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<TerminalContainer(id={self.id}, container_number='{self.container_number}', train='{self.train}')>"