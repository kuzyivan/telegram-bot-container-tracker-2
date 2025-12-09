from __future__ import annotations

from logging.config import fileConfig
import os
import sys
from typing import cast

from alembic import context
from sqlalchemy import create_engine, pool

# Добавляем корневую директорию проекта в sys.path, 
# чтобы импорты (import models, import models_finance) работали корректно
sys.path.append(os.path.join(sys.path[0], '..'))

# 1) Загружаем .env (если установлен python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 2) Берём URL: сначала ALEMBIC_DATABASE_URL (синхронный),
#    иначе DATABASE_URL (может быть async), который заменим на psycopg2
database_url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "❌ Не задан ALEMBIC_DATABASE_URL/DATABASE_URL в окружении или .env"
    )
database_url = cast(str, database_url)

# Если указан asyncpg — подменяем на psycopg2 для Alembic (он синхронный)
if database_url.startswith("postgresql+asyncpg"):
    alembic_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    print("⚡ Alembic: asyncpg → psycopg2 (для миграций)")
else:
    alembic_url = database_url

# 3) Конфиг Alembic
config = context.config
config.set_main_option("sqlalchemy.url", alembic_url)

# 4) Логирование Alembic из alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 5) ВАЖНО: импортируем Base и модели НЕ из db.py, а прямо из файлов
#    чтобы не создавать движок/сессию и не тянуть лишние зависимости
from db_base import Base # Базовый класс
import models  # Основные модели (users, tracking и т.д.)
from model.terminal_container import TerminalContainer  # Модель контейнера
import models_finance  # ✅ ФИНАНСОВЫЙ МОДУЛЬ (ОБЯЗАТЕЛЬНО)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Запуск миграций в оффлайн-режиме (генерация SQL без подключения)."""
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


def run_migrations_online() -> None:
    """Запуск миграций в онлайн-режиме (подключение к БД и применение)."""
    # создаём СИНХРОННЫЙ движок
    connectable = create_engine(
        alembic_url,
        poolclass=pool.NullPool,
        future=True,
    )

    # Просто красиво печатаем DSN без логина/пароля
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


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()