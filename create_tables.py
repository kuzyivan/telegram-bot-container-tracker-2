# create_tables.py

import asyncio
from db import engine
from model.terminal_container import TerminalContainer  # Импортируем модель, чтобы она зарегистрировалась
from models import Base

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Таблицы успешно созданы.")

if __name__ == "__main__":
    asyncio.run(main())