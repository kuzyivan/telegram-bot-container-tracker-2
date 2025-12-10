# model/terminal_container.py
"""
Определяет ORM-модель SQLAlchemy для контейнеров на терминале.
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
    """Модель для хранения информации о контейнерах на терминале (полная копия Effex)."""
    __tablename__ = 'terminal_containers'

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # --- Основная информация ---
    container_number: Mapped[str] = mapped_column(String(11), index=True, unique=True)
    client: Mapped[str | None] = mapped_column(String) # Клиент
    terminal: Mapped[str | None] = mapped_column(String) # Терминал (A-Terminal)
    zone: Mapped[str | None] = mapped_column(String) # Зона
    
    # --- Параметры контейнера ---
    container_type: Mapped[str | None] = mapped_column(String(20)) # Тип (45G1)
    size: Mapped[str | None] = mapped_column(String(20)) # Размер (40 HC)
    stock: Mapped[str | None] = mapped_column(String) # Сток
    customs_mode: Mapped[str | None] = mapped_column(String) # Таможенный режим
    direction: Mapped[str | None] = mapped_column(String) # Направление
    
    # --- Весовые характеристики ---
    payload: Mapped[float | None] = mapped_column(Float) # Грузоподъёмность
    tare: Mapped[float | None] = mapped_column(Float) # Тара
    weight_client: Mapped[float | None] = mapped_column(Float) # Брутто клиента
    weight_terminal: Mapped[float | None] = mapped_column(Float) # Брутто терминала (он же weight_brutto)
    
    # Используем weight_terminal как основной weight_brutto для совместимости
    @property
    def weight_brutto(self):
        return self.weight_terminal

    # --- Состояние и Груз ---
    state: Mapped[str | None] = mapped_column(String) # Состояние (Без повреждений)
    cargo: Mapped[str | None] = mapped_column(String) # Груз
    temperature: Mapped[str | None] = mapped_column(String) # Температура
    seals: Mapped[str | None] = mapped_column(String) # Пломбы
    
    # --- ПРИБЫТИЕ (Arrival) ---
    accept_date: Mapped[date | None] = mapped_column(Date) # Принят (Дата)
    accept_time: Mapped[time | None] = mapped_column(Time) # Принят (Время)
    in_id: Mapped[str | None] = mapped_column(String) # Id (входа)
    in_transport: Mapped[str | None] = mapped_column(String) # Транспорт (Автотягач/ЖД)
    in_number: Mapped[str | None] = mapped_column(String) # Номер вагона | Номер тягача
    in_driver: Mapped[str | None] = mapped_column(String) # Станция | Водитель
    
    # --- ОТПРАВКА (Dispatch) ---
    order_number: Mapped[str | None] = mapped_column(String) # Номер заказа
    train: Mapped[str | None] = mapped_column(String, index=True) # Поезд (Вычисляется из заказа)
    
    dispatch_date: Mapped[date | None] = mapped_column(Date) # Отправлен (Дата)
    dispatch_time: Mapped[time | None] = mapped_column(Time) # Отправлен (Время)
    out_id: Mapped[str | None] = mapped_column(String) # Id (выхода)
    out_transport: Mapped[str | None] = mapped_column(String) # Транспорт
    out_number: Mapped[str | None] = mapped_column(String) # Номер вагона | Номер тягача
    out_driver: Mapped[str | None] = mapped_column(String) # Станция | Водитель
    
    # --- Прочее ---
    release: Mapped[str | None] = mapped_column(String) # Релиз
    carrier: Mapped[str | None] = mapped_column(String) # Перевозчик
    manager: Mapped[str | None] = mapped_column(String) # Менеджер
    comment: Mapped[str | None] = mapped_column(Text) # Примечание
    
    status: Mapped[str | None] = mapped_column(String) # 'ПРИНЯТ', 'ОТГРУЖЕН' (Вычисляемое)

    # Системные поля
    weight_netto: Mapped[float | None] = mapped_column(Float) # Оставляем для совместимости
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    
    finance: Mapped["ContainerFinance"] = relationship(
        "ContainerFinance", back_populates="container", uselist=False, cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<TerminalContainer {self.container_number} ({self.status})>"