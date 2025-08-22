# model/terminal_container.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from models import Base  # ← ВАЖНО: из models, а не из db!

class TerminalContainer(Base):
    __tablename__ = "terminal_containers"

    id = Column(Integer, primary_key=True, index=True)
    container_number = Column(String, index=True, unique=True, nullable=False)
    train = Column(String, index=True, nullable=True)  # номер поезда
    terminal = Column(String)
    zone = Column(String)
    inn = Column(String)
    short_name = Column(String)
    client = Column(String)
    stock = Column(String)
    customs_mode = Column(String)
    destination_station = Column(String)
    note = Column(Text)
    raw_comment = Column(Text)
    status_comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)