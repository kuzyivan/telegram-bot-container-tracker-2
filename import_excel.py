from services.container_importer import import_loaded_and_dispatch_from_excel
import asyncio
from pathlib import Path
from datetime import datetime

async def main():
    today = datetime.now().strftime("%d.%m.%Y")
    filepath = Path(f"/root/AtermTrackBot/A-Terminal {today}.xlsx")
    await import_loaded_and_dispatch_from_excel(str(filepath))

if __name__ == "__main__":
    asyncio.run(main())