import os
import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

def get_pg_connection():
    """🔁 Старый способ подключения через psycopg2 — для существующего кода"""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT", 5432),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

def get_pg_engine() -> Engine:
    """🆕 Новый способ через SQLAlchemy — для pandas и Alembic"""
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB")

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    return create_engine(url)
