import asyncio
from sqlalchemy import text
from db import engine

async def add_overload_column():
    async with engine.begin() as conn:
        print("🛠 Добавляю колонку overload_station в scheduled_trains...")
        try:
            # Добавляем колонку, если её нет
            await conn.execute(text("ALTER TABLE scheduled_trains ADD COLUMN IF NOT EXISTS overload_station VARCHAR"))
            print("✅ Успешно! Колонка 'overload_station' добавлена.")
        except Exception as e:
            print(f"❌ Ошибка (возможно, колонка уже есть): {e}")

if __name__ == "__main__":
    asyncio.run(add_overload_column())