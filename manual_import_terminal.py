import asyncio
import logging
import sys
import os

# Добавляем текущую директорию в путь
sys.path.append(os.getcwd())

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from db import SessionLocal
# Импортируем ваш существующий сервис импорта
from services.terminal_importer import process_terminal_report_file

# Имя вашего файла (положите его в корень папки проекта)
FILENAME = "A-Terminal 11.12.2025.csv"

async def main():
    print(f"🚀 Запуск ручного импорта файла: {FILENAME}")
    
    if not os.path.exists(FILENAME):
        print(f"❌ Файл не найден! Положите {FILENAME} в папку с ботом.")
        return

    # Используем вашу асинхронную сессию
    async with SessionLocal() as session:
        try:
            # Ваш сервис сам определит, что это CSV, и использует нужный парсер
            stats = await process_terminal_report_file(session, FILENAME)
            
            print("-" * 30)
            print(f"✅ Импорт завершен!")
            print(f"📄 Файл: {stats.get('file_name')}")
            print(f"➕ Добавлено/Обработано строк: {stats.get('total_added', 0)}")
            print("-" * 30)
            
        except Exception as e:
            print(f"❌ Ошибка при импорте: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Запуск асинхронного цикла
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())