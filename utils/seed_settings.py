# utils/seed_settings.py
import asyncio
import sys
import os

# Добавляем корень проекта в путь
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db import SessionLocal
from models_finance import SystemSetting

async def seed_system_settings():
    print("🌱 Заливка базовых настроек...")
    async with SessionLocal() as session:
        settings = [
            SystemSetting(key="gondola_coeff", value="0.898", description="Коэффициент тарифа для полувагона"),
            SystemSetting(key="vat_rate", value="20.0", description="Ставка НДС по умолчанию"),
            SystemSetting(key="default_margin_fix", value="20000", description="Маржа по умолчанию (руб)"),
        ]
        
        for setting in settings:
            await session.merge(setting) 
        
        await session.commit()
        print("✅ Системные настройки (коэффициенты) обновлены.")

if __name__ == "__main__":
    asyncio.run(seed_system_settings())