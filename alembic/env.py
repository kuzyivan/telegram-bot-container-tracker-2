# alembic/env.py
from __future__ import annotations

from logging.config import fileConfig
from typing import cast
import os
import sys

from alembic import context
from sqlalchemy import pool, create_engine

# --- 0) Приводим sys.path к корню проекта, чтобы импорты работали стабильно ---
#  .../AtermTrackBot/alembic/env.py  -> корень: один уровень вверх
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- 1) Загружаем .env (если установлен python-dotenv) ---
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"))
except Exception:
    pass

# --- 2) URL БД: ALEMBIC_DATABASE_URL (sync) или DATABASE_URL (async) ---
database_url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "\n❌ DATABASE_URL/ALEMBIC_DATABASE_URL не задан(ы).\n"
        "Пример:\n"
        "  DATABASE_URL='postgresql+asyncpg://user:pass@host:5432/dbname'\n"
        "  ALEMBIC_DATABASE_URL='postgresql+psycopg2://user:pass@host:5432/dbname'\n"
    )
database_url = cast(str, database_url)

# Alembic работает синхронно → переводим asyncpg → psycopg2 при необходимости
if database_url.startswith("postgresql+asyncpg"):
    alembic_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    print("⚡️ Alembic: драйвер asyncpg → psycopg2")
else:
    alembic_url = database_url

# --- 3) Базовая конфигурация Alembic ---
config = context.config
config.set_main_option("sqlalchemy.url", alembic_url)

# --- 4) Логирование Alembic из alembic.ini ---
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- 5) Импортируем Base и модели, чтобы они попали в metadata ---
# Важно: db.py должен быть "чистым" (без импортов моделей), иначе будут циклы
from db import Base  # declarative_base()

# Явно импортируем модели (только объявления таблиц, без "тяжёлой" логики на уровне модулей)
from model.terminal_container import TerminalContainer  # noqa: F401
from models import Tracking, User, TrackingSubscription, Stats  # noqa: F401

target_metadata = Base.metadata

# --- 6) Режим "offline": генерируем SQL без подключения ---
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

# --- 7) Режим "online": подключаемся и выполняем миграции ---
def run_migrations_online() -> None:
    connectable = create_engine(
        alembic_url,
        poolclass=pool.NullPool,
        future=True,
    )

    # Покажем, куда подключаемся (без логина/пароля)
    try:
        safe_dsn = alembic_url.split("://", 1)[-1]
        if "@" in safe_dsn:
            safe_dsn = safe_dsn.split("@", 1)[-1]
        print(f"🔗 Alembic подключается к: {safe_dsn}")
    except Exception:
        pass

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

# --- 8) Точка входа ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()