# model/terminal_container.py
"""
Определяет ORM-модель SQLAlchemy для контейнеров на терминале.
"""
from sqlalchemy.orm import Mapped, mapped_column, relationship # Убедитесь, что relationship импортирован, если нужен
from sqlalchemy import (
    String, DateTime, Time, Boolean, Integer, ForeignKey, Date # Убедитесь, что все нужные типы импортированы
)
from sqlalchemy.sql import func
from datetime import datetime, date, time

# Импортируем Base из нового общего файла db_base.py
from db_base import Base

class TerminalContainer(Base):
    """Модель для хранения информации о контейнерах на терминале."""
    __tablename__ = 'terminal_containers' # Имя таблицы в базе данных

    id: Mapped[int] = mapped_column(primary_key=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True, unique=True)
    client: Mapped[str | None] = mapped_column(String)
    # Используйте Date или DateTime в зависимости от того, что вам нужно хранить
    accept_date: Mapped[date | None] = mapped_column(Date) 
    accept_time: Mapped[time | None] = mapped_column(Time)
    train: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str | None] = mapped_column(String) # Например: 'ПРИНЯТ', 'ОТГРУЖЕН'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        onupdate=func.now(), 
        server_default=func.now()
    )
    
    # --- Опционально: Добавьте связи, если они нужны ---
    # Например, если вы хотите связать контейнер с пользователем из models.py
    # user_telegram_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id")) 
    # user: Mapped["User"] = relationship() # Используйте строку "User" для связи с моделью из другого файла
    
    # --- Опционально: Метод для удобного представления ---
    def __repr__(self) -> str:
        return f"<TerminalContainer(id={self.id}, container_number='{self.container_number}', train='{self.train}')>"