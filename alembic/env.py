from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv
import os
from typing import cast

# Загрузка .env
load_dotenv()

# Получение DATABASE_URL
database_url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "\n❌ DATABASE_URL не задан в .env или переменных окружения!\n"
        "Проверь файл .env или команду export.\n"
        "Пример:\n"
        "export DATABASE_URL='postgresql+asyncpg://user:pass@host:port/db'\n"
    )
database_url = cast(str, database_url)

# Подмена asyncpg → psycopg2
if database_url.startswith("postgresql+asyncpg"):
    alembic_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    print("⚡️ Alembic: asyncpg → psycopg2 (для миграций)")
else:
    alembic_url = database_url

# Настройка Alembic
config = context.config
config.set_main_option("sqlalchemy.url", alembic_url)
print(f"🔗 Alembic подключается к базе: {alembic_url.split('@')[-1].split('?')[0]}")

# Логирование
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 👇 Подключаем метадату моделей
from models import Base  # или путь вроде app.models или bot.models
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    context.configure(
        url=alembic_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    connectable = create_engine(
        alembic_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()