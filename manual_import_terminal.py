import asyncio
import logging
import sys
import os

# Добавляем текущую директорию в путь
sys.path.append(os.getcwd())

# --- ПРАВИЛЬНЫЙ ИМПОРТ ---
try:
    # Исходя из структуры твоих файлов, db.py лежит в корне
    from db import async_session_factory
except ImportError as e:
    print(f"❌ ОШИБКА ИМПОРТА: Не удалось загрузить 'db.py'.\nДетали: {e}")
    sys.exit(1)

from services.terminal_importer import process_terminal_report_file

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FILENAME = "A-Terminal 11.12.2025.xlsx"

async def main():
    print("="*60)
    print("⚠️  ВНИМАНИЕ! Вы запускаете РУЧНОЙ импорт.")
    print(f"Файл: {FILENAME}")
    print("="*60)

    if not os.path.exists(FILENAME):
        print(f"❌ ОШИБКА: Файл '{FILENAME}' не найден в текущей папке!")
        return

    confirm = input("Введите 'y' для подтверждения: ")
    if confirm.lower() != 'y':
        print("Отмена.")
        return

    print("\n🚀 Подключаюсь к БД...")

    # Используем сессию
    async with async_session_factory() as session:
        try:
            # Передаем сессию и имя файла в функцию импорта
            await process_terminal_report_file(session, FILENAME)
            print("\n" + "="*60)
            print("🏁 ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
            print("="*60)
        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА ВО ВРЕМЯ ИМПОРТА:\n{e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Прервано пользователем.")