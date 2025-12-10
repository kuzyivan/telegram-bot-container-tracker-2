import asyncio
import os
import sys
from sqlalchemy import text

# Добавляем текущую директорию в путь, чтобы видеть модули проекта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db import SessionLocal
from services.terminal_importer import process_terminal_report_file

# ⚙️ НАСТРОЙКИ
# Укажите точное имя вашего файла
FILENAME = "A-Terminal 11.12.2025.xlsx" 

async def main():
    # 1. Проверка файла
    if not os.path.exists(FILENAME):
        print(f"❌ Файл '{FILENAME}' не найден в корневой папке!")
        print(f"Текущая папка: {os.getcwd()}")
        return

    print("="*60)
    print(f"⚠️  ВНИМАНИЕ! Вы запускаете РУЧНОЙ импорт.")
    print(f"Файл: {FILENAME}")
    print("Действие: ПОЛНАЯ ОЧИСТКА таблицы 'terminal_containers' и загрузка заново.")
    print("="*60)

    confirm = input("Введите 'y' для подтверждения или любую другую клавишу для отмены: ")
    if confirm.lower() != 'y':
        print("Отмена.")
        return

    # 2. Очистка таблицы
    print("\n🧹 Очистка базы данных...")
    async with SessionLocal() as session:
        try:
            # TRUNCATE удаляет данные мгновенно и сбрасывает ID
            await session.execute(text("TRUNCATE TABLE terminal_containers RESTART IDENTITY CASCADE;"))
            await session.commit()
            print("✅ Таблица 'terminal_containers' полностью очищена.")
        except Exception as e:
            print(f"❌ Ошибка при очистке таблицы: {e}")
            return

    # 3. Запуск импорта
    print(f"\n🚀 Начинаю обработку файла {FILENAME}...")
    try:
        # Вызываем функцию импортера
        stats = await process_terminal_report_file(FILENAME)
        
        print("\n" + "="*60)
        print("🏁 ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
        print("="*60)
        print(f"📥 Добавлено (новых записей): {stats.get('added', 0)}")
        print(f"🔄 Обновлено (существующих):  {stats.get('updated', 0)}")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Критическая ошибка при импорте: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Настройка для Windows (если запускаешь локально), на Linux не мешает
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Скрипт остановлен пользователем.")