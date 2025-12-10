# model/terminal_container.py
"""
Определяет ORM-модель SQLAlchemy для контейнеров на терминале.
Полная копия структуры отчета Effex (A-Terminal).
"""
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Time, Date, Float, Integer, Text
from sqlalchemy.sql import func
from datetime import datetime, date, time

from db_base import Base

if TYPE_CHECKING:
    from models_finance import ContainerFinance

class TerminalContainer(Base):
    """Модель для хранения информации о контейнерах на терминале (зеркало Effex)."""
    __tablename__ = 'terminal_containers'

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # --- Блок 1: Идентификация и Локация ---
    container_number: Mapped[str] = mapped_column(String(11), index=True, unique=True) # Контейнер
    terminal: Mapped[str | None] = mapped_column(String) # Терминал
    zone: Mapped[str | None] = mapped_column(String) # Зона
    client: Mapped[str | None] = mapped_column(String) # Клиент
    
    # 🔥 ДОБАВЛЕНЫ НЕДОСТАЮЩИЕ ПОЛЯ ИЗ ВАШЕГО CSV
    inn: Mapped[str | None] = mapped_column(String) # ИНН
    short_name: Mapped[str | None] = mapped_column(String) # Краткое наименование
    
    stock: Mapped[str | None] = mapped_column(String) # Сток
    
    # --- Блок 2: Параметры груза и контейнера ---
    customs_mode: Mapped[str | None] = mapped_column(String) # Таможенный режим
    direction: Mapped[str | None] = mapped_column(String) # Направление
    container_type: Mapped[str | None] = mapped_column(String(20)) # Тип
    size: Mapped[str | None] = mapped_column(String(20)) # Размер
    payload: Mapped[float | None] = mapped_column(Float) # Грузоподъёмность
    tare: Mapped[float | None] = mapped_column(Float) # Тара
    
    # 🔥 ЕЩЕ ОДНО ВОЗМОЖНОЕ ПОЛЕ (если есть в CSV 'Год изготовления')
    manufacture_year: Mapped[str | None] = mapped_column(String) 
    
    # --- Блок 3: Веса ---
    weight_client: Mapped[float | None] = mapped_column(Float) # Брутто клиента
    weight_terminal: Mapped[float | None] = mapped_column(Float) # Брутто терминала
    
    @property
    def weight_brutto(self):
        return self.weight_terminal

    # --- Блок 4: Состояние ---
    state: Mapped[str | None] = mapped_column(String) # Состояние
    cargo: Mapped[str | None] = mapped_column(String) # Груз
    temperature: Mapped[str | None] = mapped_column(String) # Температура
    seals: Mapped[str | None] = mapped_column(String) # Пломбы
    
    # --- Блок 5: ПРИБЫТИЕ ---
    accept_date: Mapped[date | None] = mapped_column(Date) 
    accept_time: Mapped[time | None] = mapped_column(Time) 
    in_id: Mapped[str | None] = mapped_column(String) 
    in_transport: Mapped[str | None] = mapped_column(String) 
    in_number: Mapped[str | None] = mapped_column(String) 
    in_driver: Mapped[str | None] = mapped_column(String) 
    
    # --- Блок 6: ЗАКАЗ И ОТПРАВКА ---
    order_number: Mapped[str | None] = mapped_column(String) 
    train: Mapped[str | None] = mapped_column(String, index=True) 
    
    dispatch_date: Mapped[date | None] = mapped_column(Date) 
    dispatch_time: Mapped[time | None] = mapped_column(Time) 
    out_id: Mapped[str | None] = mapped_column(String) 
    out_transport: Mapped[str | None] = mapped_column(String) 
    out_number: Mapped[str | None] = mapped_column(String) 
    out_driver: Mapped[str | None] = mapped_column(String) 
    
    # --- Блок 7: Прочее ---
    release: Mapped[str | None] = mapped_column(String) 
    carrier: Mapped[str | None] = mapped_column(String) 
    manager: Mapped[str | None] = mapped_column(String) 
    comment: Mapped[str | None] = mapped_column(Text) 
    
    status: Mapped[str | None] = mapped_column(String) 

    # Системные поля
    weight_netto: Mapped[float | None] = mapped_column(Float) 
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    
    finance: Mapped["ContainerFinance"] = relationship(
        "ContainerFinance", back_populates="container", uselist=False, cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<TerminalContainer {self.container_number} ({self.status})>"