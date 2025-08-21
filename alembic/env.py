# alembic/env.py
from __future__ import annotations

from logging.config import fileConfig
from typing import cast
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy import create_engine

# 1) Загружаем переменные окружения из .env (если используешь python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # не критично, если нет python-dotenv — предполагаем, что переменные уже заданы в окружении
    pass

# 2) Берём URL из ALEMBIC_DATABASE_URL или DATABASE_URL
database_url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "\n❌ DATABASE_URL/ALEMBIC_DATABASE_URL не задан(ы) в окружении.\n"
        "Пример:\n"
        "  export DATABASE_URL='postgresql+asyncpg://user:pass@host:5432/dbname'\n"
        "или специально для миграций (синхронный драйвер):\n"
        "  export ALEMBIC_DATABASE_URL='postgresql+psycopg2://user:pass@host:5432/dbname'\n"
    )
database_url = cast(str, database_url)

# 3) Alembic работает СИНХРОННО, поэтому переводим async URL → psycopg2
if database_url.startswith("postgresql+asyncpg"):
    alembic_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    print("⚡️ Alembic: драйвер asyncpg → psycopg2 (для миграций)")
else:
    alembic_url = database_url

# 4) Базовая конфигурация Alembic
config = context.config
# прокидываем URL в конфиг Alembic
config.set_main_option("sqlalchemy.url", alembic_url)

# 5) Логирование Alembic (alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 6) Импортируем Base и ВСЕ модели, чтобы они попали в metadata
#    ВАЖНО: импортируй всё, где объявлены таблицы
from models import Base  # ваш общий Base (declarative_base)
# Явно импортируем TerminalContainer, чтобы Alembic её увидел:
from model.terminal_container import TerminalContainer  # noqa: F401

# Если есть другие модели в отдельных модулях — импортируй их здесь аналогично:
# from models import Tracking, User, TrackingSubscription, Stats  # noqa: F401

target_metadata = Base.metadata

# ————————————————————————————————————————————————————————————————
# Функции оффлайн/онлайн миграций
# ————————————————————————————————————————————————————————————————
def run_migrations_offline() -> None:
    """
    Запуск миграций в 'offline' режиме.
    Только генерим SQL, без реального подключения к БД.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,         # учитывать изменения типов колонок
        compare_server_default=True,  # и дефолтов (при желании можно убрать)
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Запуск миграций в 'online' режиме.
    Создаём синхронный движок (psycopg2) и применяем миграции.
    """
    connectable = create_engine(
        alembic_url,
        poolclass=pool.NullPool,
        future=True,  # новый стиль SQLAlchemy
    )

    # Красиво печатаем «куда» подключаемся, без логина/пароля
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
            compare_type=True,           # учитывать изменения типов
            compare_server_default=True, # учитывать изменения server_default
        )

        with context.begin_transaction():
            context.run_migrations()


# ————————————————————————————————————————————————————————————————
# Точка входа
# ————————————————————————————————————————————————————————————————
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()