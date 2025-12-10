import asyncio
import logging
import sys
import os

# Добавляем текущую директорию в путь, чтобы Python видел модули проекта
sys.path.append(os.getcwd())

# --- БЛОК ИМПОРТОВ БД ---
# ВАЖНО: Проверь, что путь к async_session_factory правильный для твоего проекта
try:
    from database.db import async_session_factory
except ImportError:
    try:
        # Попытка альтернативного импорта, если первый не сработал
        from database import async_session_factory
    except ImportError:
        print("❌ ОШИБКА: Не могу найти async_session_factory.")
        print("Проверь в файле manual_import_terminal.py строку: from database.db import async_session_factory")
        sys.exit(1)

from services.terminal_importer import process_terminal_report_file

# Настройка простого логирования для консоли
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Имя файла для импорта
FILENAME = "A-Terminal 11.12.2025.xlsx"

async def main():
    print("="*60)
    print("⚠️  ВНИМАНИЕ! Вы запускаете РУЧНОЙ импорт.")
    print(f"Файл: {FILENAME}")
    print("Действие: Загрузка данных в таблицу 'terminal_containers'.")
    print("="*60)

    # Проверка наличия файла
    if not os.path.exists(FILENAME):
        print(f"❌ ОШИБКА: Файл '{FILENAME}' не найден в текущей папке!")
        return

    confirm = input("Введите 'y' для подтверждения или любую другую клавишу для отмены: ")
    if confirm.lower() != 'y':
        print("Отмена.")
        return

    print("\n🚀 Подключаюсь к БД и начинаю обработку...")

    # Создаем сессию БД (контекстный менеджер сам её закроет)
    async with async_session_factory() as session:
        try:
            # ВЫЗОВ ФУНКЦИИ ИМПОРТА
            # Передаем сессию первым аргументом, путь к файлу вторым
            await process_terminal_report_file(session, FILENAME)
            
            print("\n" + "="*60)
            print("🏁 ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
            print("="*60)
            
        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА во время импорта:\n{e}")
            # Полный трейсбек для отладки
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        # Запуск асинхронного цикла
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Прервано пользователем.")
    except SystemExit:
        pass