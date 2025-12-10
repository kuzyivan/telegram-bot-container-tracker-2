import asyncio
import os
import sys
from sqlalchemy import text

# Добавляем путь к корню проекта, чтобы Python видел папки services, db и т.д.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db import SessionLocal
from services.terminal_importer import process_terminal_report_file

# Имя файла для импорта
FILENAME = "A-Terminal 11.12.2025.xlsx"

async def main():
    # 1. Проверка наличия файла
    if not os.path.exists(FILENAME):
        print(f"❌ Файл '{FILENAME}' не найден в корневой папке!")
        print("Пожалуйста, загрузите файл на сервер и проверьте имя.")
        return

    # 2. Предупреждение
    print("="*50)
    print(f"⚠️  ВНИМАНИЕ! Вы запускаете РУЧНОЙ импорт из файла: {FILENAME}")
    print("Этот скрипт ПОЛНОСТЬЮ ОЧИСТИТ (удалит все данные) таблицу 'terminal_containers'.")
    print("="*50)
    
    confirm = input("Вы уверены, что хотите продолжить? Введите 'y' для старта: ")
    if confirm.lower() != 'y':
        print("Отмена операции.")
        return

    # 3. Очистка таблицы
    print("\n🧹 Очистка базы данных...")
    async with SessionLocal() as session:
        try:
            # TRUNCATE удаляет данные мгновенно и сбрасывает счетчик ID
            await session.execute(text("TRUNCATE TABLE terminal_containers RESTART IDENTITY CASCADE;"))
            await session.commit()
            print("✅ Таблица terminal_containers успешно очищена.")
        except Exception as e:
            print(f"❌ Ошибка при очистке таблицы: {e}")
            return

    # 4. Запуск импорта
    print(f"\n🚀 Начинаю импорт данных из {FILENAME}...")
    try:
        stats = await process_terminal_report_file(FILENAME)
        
        print("\n" + "="*50)
        print("🏁 ИМПОРТ ЗАВЕРШЕН!")
        print("="*50)
        print(f"📥 Добавлено новых записей (Arrival): {stats.get('added', 0)}")
        print(f"🔄 Обновлено записей (Dispatch):     {stats.get('updated', 0)}")
        print("="*50)
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка во время импорта: {e}")

if __name__ == "__main__":
    # Фикс для Windows (если запускаешь локально), на Linux не мешает
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(main())