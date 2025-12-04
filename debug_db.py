import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

load_dotenv()
TARIFF_DB_URL = os.getenv("TARIFF_DATABASE_URL")

async def check_station(code_6: str):
    if not TARIFF_DB_URL:
        print("❌ Ошибка: TARIFF_DATABASE_URL не найден в .env")
        return

    engine = create_async_engine(TARIFF_DB_URL, echo=False)
    
    # Пробуем и 6 знаков, и 5 знаков
    code_5 = code_6[:-1]
    
    print(f"🔎 Ищем станцию с кодом {code_6} или {code_5} в таблице railway_sections...")
    
    # ИСПРАВЛЕННЫЙ SQL ЗАПРОС (используем CAST вместо ::)
    sql = text("""
        SELECT id, source_file, stations_list 
        FROM railway_sections 
        WHERE stations_list @> CAST(:json_6 AS jsonb) 
           OR stations_list @> CAST(:json_5 AS jsonb)
        LIMIT 3
    """)
    
    json_6 = f'[{{"c": "{code_6}"}}]'
    json_5 = f'[{{"c": "{code_5}"}}]'
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sql, {"json_6": json_6, "json_5": json_5})
            rows = result.fetchall()
            
            if not rows:
                print("❌ Станция НЕ НАЙДЕНА в базе Book 1.")
                print("   Возможные причины:")
                print("   1. Ошибка при миграции (book_1_migrator.py).")
                print("   2. Станция находится в файле, который не был распарсен.")
            else:
                print(f"✅ Станция найдена в {len(rows)} записях!")
                for row in rows:
                    file_name = row[1]
                    data = row[2] # stations_list
                    print(f"\n   📂 Файл: {file_name}")
                    print(f"   🚉 Всего станций в цепочке: {len(data)}")
                    
                    # Найдем позицию станции в списке
                    for i, st in enumerate(data):
                        if st['c'] == code_5 or st['c'] == code_6:
                            print(f"      📍 Позиция {i}: {st['n']} (Код: {st['c']})")
                            
                            # Покажем соседей для проверки
                            start_idx = max(0, i - 1)
                            end_idx = min(len(data), i + 2)
                            neighbors = [s['n'] for s in data[start_idx:end_idx]]
                            print(f"      🔗 Соседи: ... {' -> '.join(neighbors)} ...")
                            break

    except Exception as e:
        print(f"💥 Ошибка выполнения запроса: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    # Проверяем Угловую (982206)
    asyncio.run(check_station("982206"))