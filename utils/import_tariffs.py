import asyncio
import os
import sys
import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db import SessionLocal
from models_finance import RailTariffRate

# --- ⚙️ НАСТРОЙКИ ---
EXCEL_FILE = "tariffs.xlsx"

# Названия колонок в Excel
COL_FROM = 'station_from'
COL_TO = 'station_to'
COL_SERVICE = 'service_type' # ✅ НОВАЯ КОЛОНКА

# Маппинг цен
RATE_COLUMNS_MAP = {
    'rate_20_ref':   '20_REF',
    'rate_20_heavy': '20_HEAVY',
    'rate_20_extra': '20_EXTRA',
    'rate_40_std':   '40_STD',
    'rate_40_heavy': '40_HEAVY'
}

# Словарь подмены городов
STATION_TRANSLATOR = {
    "МОСКВА":          "181102",  # Селятино
    "НОВОСИБИРСК":     "850308",  # Чемской
    "УГЛОВАЯ":         "984700",
    "ВЛАДИВОСТОК":     "980003",
    "ЕКАТЕРИНБУРГ":    "780308",
    "ИРКУТСК":         "932601",
    "КРАСНОЯРСК":      "890006",
}

def resolve_code(name_raw: str) -> str | None:
    if pd.isna(name_raw) or str(name_raw).strip() == "": return None
    val_str = str(name_raw).strip().upper().split('.')[0]
    if val_str in STATION_TRANSLATOR: return STATION_TRANSLATOR[val_str]
    if val_str.isdigit() and len(val_str) >= 4: return val_str
    return None

def resolve_service_type(val_raw: str) -> str:
    """Определяет тип сервиса: TRAIN или SINGLE"""
    if pd.isna(val_raw):
        return 'TRAIN' # По умолчанию - Поезд
    
    val = str(val_raw).strip().upper()
    
    if 'ОДИН' in val or 'SINGLE' in val:
        return 'SINGLE'
    
    return 'TRAIN'

async def import_tariffs():
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Файл {EXCEL_FILE} не найден.")
        return

    print(f"📂 Чтение {EXCEL_FILE}...")
    try:
        df = pd.read_excel(EXCEL_FILE, dtype=str)
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return

    tariffs_to_insert = []
    
    print("🔄 Обработка данных...")

    for index, row in df.iterrows():
        try:
            # 1. Коды станций
            name_from = row.get(COL_FROM)
            name_to = row.get(COL_TO)
            code_from = resolve_code(name_from)
            code_to = resolve_code(name_to)

            if not code_from or not code_to:
                continue

            # 2. ✅ ОПРЕДЕЛЕНИЕ ТИПА СЕРВИСА (Поезд или Одиночка)
            # Если колонки нет в файле, по умолчанию будет TRAIN
            raw_service = row.get(COL_SERVICE)
            service_type = resolve_service_type(raw_service)

            # 3. Цены
            for excel_col, db_type in RATE_COLUMNS_MAP.items():
                if excel_col not in df.columns: continue
                
                raw_price = row.get(excel_col)
                if pd.isna(raw_price) or str(raw_price).strip() == "": continue

                try:
                    price_val = float(str(raw_price).replace(' ', '').replace(',', '.'))
                    if price_val <= 0: continue

                    tariffs_to_insert.append({
                        "station_from_code": code_from,
                        "station_to_code": code_to,
                        "container_type": db_type,
                        "service_type": service_type, # Пишем в базу (TRAIN или SINGLE)
                        "rate_no_vat": price_val
                    })
                except ValueError:
                    continue

        except Exception as e:
            print(f"⚠️ Ошибка в строке {index+2}: {e}")

    if not tariffs_to_insert:
        print("⚠️ Нет данных.")
        return

    print(f"🚀 Запись {len(tariffs_to_insert)} тарифов в БД...")

    async with SessionLocal() as session:
        stmt = pg_insert(RailTariffRate).values(tariffs_to_insert)
        
        # Обновляем при совпадении (Откуда + Куда + ТипКонтейнера + ТипСервиса)
        upsert_stmt = stmt.on_conflict_do_update(
            constraint='uq_tariff_route_type_service',
            set_={
                "rate_no_vat": stmt.excluded.rate_no_vat,
                "updated_at": func.now()
            }
        )

        try:
            await session.execute(upsert_stmt)
            await session.commit()
            print(f"✅ УСПЕШНО! Обработано записей: {len(tariffs_to_insert)}")
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка SQL: {e}")

if __name__ == "__main__":
    asyncio.run(import_tariffs())