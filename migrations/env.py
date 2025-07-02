from logging.config import fileConfig
import os
from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Загружаем переменные окружения из .env
load_dotenv()

# Импортируем объект Base из models.py
from models import Base

print(f"🔗 Alembic подключается к: {os.getenv('ALEMBIC_DATABASE_URL')}")

# Конфигурация Alembic
config = context.config

# Загружаем значение DATABASE_URL из .env
config.set_main_option('sqlalchemy.url', os.getenv("ALEMBIC_DATABASE_URL")) # type: ignore

# Интерпретируем конфигурационный файл логирования
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,  # Чтобы учитывать изменение типов
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), # type: ignore
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
