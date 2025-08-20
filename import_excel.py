import asyncio
from pathlib import Path
from services.container_importer import import_loaded_and_dispatch_from_excel
from logger import get_logger

logger = get_logger(__name__)

async def main():
    today_file = Path("/root/AtermTrackBot/A-Terminal 20.08.2025.xlsx")  # Укажи нужную дату, если файл отличается
    if today_file.exists():
        await import_loaded_and_dispatch_from_excel(str(today_file))
    else:
        logger.error(f"❌ Файл не найден: {today_file}")

if __name__ == "__main__":
    asyncio.run(main())