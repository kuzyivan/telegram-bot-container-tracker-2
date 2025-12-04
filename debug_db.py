import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

async def check_station(code_6: str):
    engine = create_async_engine(TARIFF_DB_URL, echo=False)
    
    # Пробуем и 6 знаков, и 5 знаков (так как в Книге 1 коды часто без контрольного числа)
    code_5 = code_6[:-1]
    
    print(f"🔎 Ищем станцию с кодом {code_6} или {code_5} в таблице railway_sections...")
    
    sql = text("""
        SELECT id, source_file, stations_list 
        FROM railway_sections 
        WHERE stations_list @> :json_6::jsonb 
           OR stations_list @> :json_5::jsonb
        LIMIT 3
    """)
    
    json_6 = f'[{{"c": "{code_6}"}}]'
    json_5 = f'[{{"c": "{code_5}"}}]'
    
    async with engine.connect() as conn:
        result = await conn.execute(sql, {"json_6": json_6, "json_5": json_5})
        rows = result.fetchall()
        
        if not rows:
            print("❌ Станция НЕ НАЙДЕНА в базе Book 1. Проверь book_1_migrator.py еще раз.")
        else:
            print(f"✅ Станция найдена в {len(rows)} записях!")
            for row in rows:
                data = row[2] # stations_list
                print(f"   📂 Файл: {row[1]}")
                print(f"   🚉 Всего станций в цепочке: {len(data)}")
                # Выведем 3 станции до и 3 после
                found_idx = -1
                for i, st in enumerate(data):
                    if st['c'] == code_5 or st['c'] == code_6:
                        found_idx = i
                        print(f"      📍 ПОЗИЦИЯ {i}: {st['n']} ({st['c']})")
                        break

    await engine.dispose()

if __name__ == "__main__":
    # Проверяем Угловую (982206)
    asyncio.run(check_station("982206"))