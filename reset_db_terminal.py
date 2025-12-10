import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import DATABASE_URL

async def reset_terminal_table():
    print(f"🔥 Подключение к БД: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        print("🗑 Удаляю таблицу terminal_containers...")
        await conn.execute(text("DROP TABLE IF EXISTS terminal_containers CASCADE;"))
        
        print("🗑 Очищаю историю миграций (удаляю таблицу alembic_version)...")
        # Мы удаляем alembic_version, чтобы Alembic "забыл" обо всех примененных миграциях
        # и позволил нам создать новую инициализирующую миграцию.
        # ВНИМАНИЕ: Это безопасно, если у вас нет ДРУГИХ важных таблиц, которые управляются Alembic.
        # Если есть другие таблицы (users, tracking), то лучше удалить только запись о конкретной ревизии.
        # Но для радикального решения проблем с "Can't locate revision" это самый верный способ.
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version;"))
        
    print("✅ База очищена от старой таблицы терминала.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_terminal_table())