# db_base.py
"""
Определяет базовый класс DeclarativeBase для SQLAlchemy.
Вынесен сюда, чтобы избежать циклических импортов между файлами моделей.
"""
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass