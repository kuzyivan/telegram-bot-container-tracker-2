# models.py
"""
Определяет основные ORM-модели SQLAlchemy для бота,
кроме TerminalContainer, которая находится в model/terminal_container.py.
"""
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String, Float, Integer, BigInteger, DateTime, Time, ARRAY, ForeignKey, Text, Boolean, Date
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
    
    email: Mapped[str] = mapped_column(String, index=True) 
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False) 
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связь обратно к User
    user: Mapped["User"] = relationship(back_populates="emails")

# --- НОВАЯ МОДЕЛЬ ДЛЯ ХРАНЕНИЯ КОДА ПОДТВЕРЖДЕНИЯ ---
class VerificationCode(Base):
    """Временная модель для хранения кода подтверждения email."""
    __tablename__ = "email_verification_codes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String(6))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
# ----------------------------------------------------


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


# =========================================================================
# === 4. ОБНОВЛЕННАЯ МОДЕЛЬ TRACKING (45+ полей) ===
# =========================================================================
class Tracking(Base):
    """
    Модель для хранения данных дислокации.
    Поддерживает как старый (10-12 полей), так и новый (45 полей) формат РЖД.
    """
    __tablename__ = "tracking"

    # --- Системные и основные поля ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    container_number: Mapped[str] = mapped_column(String(11), index=True, nullable=False)
    
    # --- Данные о рейсе (из нового файла) ---
    trip_start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    trip_end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    # --- Данные Отправления ---
    from_state: Mapped[str | None] = mapped_column(String)
    from_road: Mapped[str | None] = mapped_column(String)
    from_station: Mapped[str | None] = mapped_column(String)
    
    # --- Данные Назначения ---
    to_country: Mapped[str | None] = mapped_column(String)
    to_road: Mapped[str | None] = mapped_column(String)
    to_station: Mapped[str | None] = mapped_column(String)

    # --- Данные о Грузоотправителе ---
    sender_tgnl: Mapped[str | None] = mapped_column(String)
    sender_name_short: Mapped[str | None] = mapped_column(String)
    sender_okpo: Mapped[str | None] = mapped_column(String(10))
    sender_name: Mapped[str | None] = mapped_column(String)

    # --- Данные о Грузополучателе ---
    receiver_tgnl: Mapped[str | None] = mapped_column(String)
    receiver_name_short: Mapped[str | None] = mapped_column(String)
    receiver_okpo: Mapped[str | None] = mapped_column(String(10))
    receiver_name: Mapped[str | None] = mapped_column(String)

    # --- Данные о Грузе ---
    container_type: Mapped[str | None] = mapped_column(String)
    cargo_name: Mapped[str | None] = mapped_column(String)
    cargo_gng_code: Mapped[str | None] = mapped_column(String(12))
    cargo_weight_kg: Mapped[int | None] = mapped_column(Integer)
    is_loaded_trip: Mapped[bool | None] = mapped_column(Boolean)

    # --- Данные о Текущей Дислокации ---
    current_station: Mapped[str | None] = mapped_column(String)
    operation: Mapped[str | None] = mapped_column(String)
    operation_road: Mapped[str | None] = mapped_column(String)
    operation_mnemonic: Mapped[str | None] = mapped_column(String(10))
    operation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True) # Важно для сортировки
    container_state: Mapped[str | None] = mapped_column(String)

    # --- Данные о Поезде и Вагоне ---
    train_index_full: Mapped[str | None] = mapped_column(String)
    train_number: Mapped[str | None] = mapped_column(String, index=True) # <--- Это номер поезда РЖД (напр. "3005")
    wagon_number: Mapped[str | None] = mapped_column(String, index=True)
    seals_count: Mapped[int | None] = mapped_column(Integer)
    
    # --- Данные о Приеме/Сдаче ---
    accept_state: Mapped[str | None] = mapped_column(String)
    surrender_state: Mapped[str | None] = mapped_column(String)
    accept_road: Mapped[str | None] = mapped_column(String)
    surrender_road: Mapped[str | None] = mapped_column(String)
    
    # --- Данные о Доставке и Расстояниях ---
    delivery_deadline: Mapped[date | None] = mapped_column(Date) # 'Нормативный срок доставки' (21.01.2025)
    total_distance: Mapped[int | None] = mapped_column(Integer)
    distance_traveled: Mapped[int | None] = mapped_column(Integer)
    km_left: Mapped[int | None] = mapped_column(Integer) # 'Расстояние оставшееся'
    
    # --- Данные о Простое ---
    last_op_idle_time_str: Mapped[str | None] = mapped_column(String)
    last_op_idle_days: Mapped[float | None] = mapped_column(Float)
    
    # --- Идентификаторы ---
    waybill: Mapped[str | None] = mapped_column(String) # 'Номер накладной' (ЭЛ970932)
    dispatch_id: Mapped[str | None] = mapped_column(String) # 'Идентификатор отправки'
    waybill_id: Mapped[int | None] = mapped_column(BigInteger, index=True) # 'Идентификатор накладной' (1576096824)

    # --- Старое поле (на всякий случай, если оно используется) ---
    forecast_days: Mapped[float | None] = mapped_column(Float)

# =========================================================================


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


# --- ✅ ОБНОВЛЕННАЯ МОДЕЛЬ: ТАБЛИЦА ПОЕЗДОВ ---
class Train(Base):
    """
    Централизованная таблица для отслеживания АКТУАЛЬНОГО СТАТУСА
    каждого поезда, агрегируя данные из Tracking и TerminalContainer.
    """
    __tablename__ = "trains"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # 1. Ключевая информация (из файла поезда)
    terminal_train_number: Mapped[str] = mapped_column(String(50), unique=True, index=True) # № поезда (К25-103)
    container_count: Mapped[int | None] = mapped_column(Integer) # Кол-во контейнеров
    
    # 2. Маршрут (из файла поезда или дислокации)
    destination_station: Mapped[str | None] = mapped_column(String, index=True)
    departure_date: Mapped[date | None] = mapped_column(Date)

    # 3. Информация о перегрузе (из диалога с админом)
    overload_station_name: Mapped[str | None] = mapped_column(String, nullable=True)
    overload_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 4. Динамический статус (обновляется из dislocation_importer)
    rzd_train_number: Mapped[str | None] = mapped_column(String, index=True, nullable=True) # (e.g., "3005")
    last_known_station: Mapped[str | None] = mapped_column(String)
    last_known_road: Mapped[str | None] = mapped_column(String)
    last_operation: Mapped[str | None] = mapped_column(String)
    last_operation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False)) # <-- Используем False, как в Tracking
    
    # 5. Прогноз (обновляется из dislocation_importer)
    km_remaining: Mapped[int | None] = mapped_column(Integer)
    eta_days: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


# =========================================================================
# === ✅ НОВАЯ МОДЕЛЬ: ПРАВИЛА УВЕДОМЛЕНИЙ О СОБЫТИЯХ ===
# =========================================================================
class EventAlertRule(Base):
    """
    Таблица для хранения правил уведомлений о событиях поезда.
    Отвечает на вопросы: КОГО, КУДА, О ЧЕМ и ПОЧЕМУ уведомлять.
    """
    __tablename__ = "event_alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Понятное имя, чтобы админ не запутался (н-р, "Выгрузка для клиента А", "Админ: все события")
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # 1. ЧТО случилось? (Триггер)
    # Возможные значения: 'UNLOAD', 'DEPARTURE', 'OVERLOAD_ARRIVAL', 'IDLE_48H', 'ALL'
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # 2. КУДА отправить? (Канал)
    # Возможные значения: 'EMAIL', 'TELEGRAM'
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # 3. КОГО уведомить? (Получатель)
    # Если channel='EMAIL'
    recipient_email: Mapped[str | None] = mapped_column(String, nullable=True)
    # Если channel='TELEGRAM'
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="SET NULL"), 
        nullable=True
    )

    # 4. ЗА ЧЕМ следить? (Область видимости)
    # Если NULL -> Глобальное правило (все поезда)
    # Если ID -> Только для контейнеров из этой подписки
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), 
        nullable=True
    )

    # Связи (для удобства)
    user: Mapped["User" | None] = relationship()
    subscription: Mapped["Subscription" | None] = relationship()

    def __repr__(self) -> str:
        return f"<EventAlertRule(id={self.id}, name='{self.rule_name}', event='{self.event_type}', channel='{self.channel}')>"