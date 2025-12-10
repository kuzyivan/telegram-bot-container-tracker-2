import asyncio
import logging
import sys
import os

# Добавляем текущую директорию в путь, чтобы Python видел модули проекта
sys.path.append(os.getcwd())

# --- НАСТРОЙКА ЛОГГЕРА ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- ИМПОРТЫ ---
try:
    # Импортируем SessionLocal из твоего файла db.py
    # и сразу переименовываем для понятности в async_session_factory
    from db import SessionLocal as async_session_factory
except ImportError as e:
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА: Не удалось загрузить SessionLocal из 'db.py'.")
    logger.error(f"Детали: {e}")
    sys.exit(1)

try:
    from services.terminal_importer import process_terminal_report_file
except ImportError as e:
    logger.error(f"❌ ОШИБКА: Не найден модуль services.terminal_importer.")
    logger.error(f"Детали: {e}")
    sys.exit(1)

# Имя файла для импорта
FILENAME = "A-Terminal 11.12.2025.xlsx"

async def main():
    print("="*60)
    print("⚠️  ВНИМАНИЕ! Вы запускаете РУЧНОЙ импорт.")
    print(f"Файл: {FILENAME}")
    print("="*60)

    # Проверка наличия файла
    if not os.path.exists(FILENAME):
        print(f"❌ ОШИБКА: Файл '{FILENAME}' не найден в текущей папке!")
        print(f"📂 Текущая папка: {os.getcwd()}")
        return

    confirm = input("Введите 'y' для подтверждения начала загрузки: ")
    if confirm.lower() != 'y':
        print("Отмена операции.")
        return

    print("\n🚀 Подключаюсь к базе данных...")

    # Создаем сессию и передаем её в импортер
    async with async_session_factory() as session:
        try:
            # Запускаем процесс
            await process_terminal_report_file(session, FILENAME)
            
            print("\n" + "="*60)
            print("🏁 ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
            print("="*60)
            
        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА ВО ВРЕМЯ ВЫПОЛНЕНИЯ:\n{e}")
            # Выводим полный стек ошибки для отладки
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        # Настройка цикла событий для Windows (если вдруг запустишь там)
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Скрипт остановлен пользователем.")
    except SystemExit:
        pass