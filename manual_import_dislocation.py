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
from services.dislocation.service import process_dislocation_file

# Имя файла для теста (положите файл дислокации в корень проекта)
FILENAME = "dislocation_report.xlsx"

async def main():
    print(f"🚀 Запуск ручного импорта дислокации: {FILENAME}")
    
    if not os.path.exists(FILENAME):
        print(f"❌ Файл не найден! Положите {FILENAME} в папку проекта.")
        return

    async with SessionLocal() as session:
        try:
            stats = await process_dislocation_file(session, FILENAME)
            
            print("-" * 30)
            if stats['status'] == 'success':
                print(f"✅ Импорт успешно завершен!")
                print(f"📄 Файл: {stats.get('file')}")
                print(f"📊 Всего строк: {stats.get('total_rows')}")
                print(f"➕ Добавлено новых: {stats.get('inserted')}")
                print(f"🔄 Обновлено: {stats.get('updated')}")
                print(f"🚆 Обновлено поездов: {stats.get('trains_updated')}")
            else:
                print(f"❌ Ошибка: {stats.get('error')}")
            print("-" * 30)
            
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())