from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from dotenv import load_dotenv
import os
from typing import cast

# Загружаем переменные окружения из .env
load_dotenv()

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "\n❌ DATABASE_URL не задан в .env или переменных окружения!\n"
        "Проверь файл .env или команду export.\n"
        "Пример:\n"
        "export DATABASE_URL='postgresql+asyncpg://user:pass@host:port/db?sslmode=require'\n"
    )
database_url = cast(str, database_url)

# Alembic Config
config = context.config
config.set_main_option('sqlalchemy.url', database_url)
print(f"🔗 Alembic подключается к базе: {database_url.split('@')[-1].split('?')[0]}")  # не светим пароль

# Логирование
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Импортируй свои модели сюда для autogenerate
# from src.models import Base
target_metadata = None  # Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy import create_engine
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
