import asyncio
from db import SessionLocal
from services.calculator_service import PriceCalculator

# ✅ ВАЖНО: Все значения должны быть в кавычках "..."
FROM_CODE = "984700"  # Угловая
TO_CODE = "181102"    # Москва (Селятино)
TYPE = "40_STD"       # Тип контейнера (как в базе/Excel)
SERVICE = "TRAIN"     # Тип сервиса (TRAIN или SINGLE)

async def test():
    async with SessionLocal() as session:
        calc = PriceCalculator(session)
        
        print(f"🧮 Пробуем посчитать: {FROM_CODE} -> {TO_CODE} ({TYPE})")
        
        result = await calc.calculate_price(FROM_CODE, TO_CODE, TYPE, SERVICE)
        
        if result.get("success"):
            print("-" * 30)
            print(f"✅ Тариф найден!")
            print(f"Маршрут:        {result['station_from']} -> {result['station_to']}")
            print(f"База (Закуп):   {result['base_rate']:,.2f} руб.")
            print(f"Маржа:          {result['margin']:,.2f} руб.")
            print(f"Цена без НДС:   {result['price_no_vat']:,.2f} руб.")
            print(f"НДС (22%):      {result['vat_amount']:,.2f} руб.")
            print("-" * 30)
            print(f"💰 ИТОГО:       {result['total_price']:,.2f} руб.")
            print("-" * 30)
        else:
            print(f"❌ Ошибка: {result.get('error')}")
            print(f"Детали: {result.get('details')}")

if __name__ == "__main__":
    asyncio.run(test())