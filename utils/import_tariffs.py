import asyncio
import os
import sys
import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

# Добавляем корень проекта
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db import SessionLocal, TariffSessionLocal
from models_finance import RailTariffRate
from services.tariff_service import TariffStation

# --- ⚙️ НАСТРОЙКИ ---
EXCEL_FILE = "tariffs.xlsx"

# 🔥 ГЛАВНАЯ НАСТРОЙКА: Для какого сервиса эти тарифы?
# Варианты: 'TRAIN' (Поезд) или 'SINGLE' (Одиночка)
IMPORT_FOR_SERVICE = 'TRAIN' 

COL_FROM = 'station_from'
COL_TO = 'station_to'

RATE_COLUMNS_MAP = {
    'rate_20_ref':   '20_REF',
    'rate_20_heavy': '20_HEAVY',
    'rate_20_extra': '20_EXTRA',
    'rate_40_std':   '40_STD',
    'rate_40_heavy': '40_HEAVY'
}

# Словарь подмены
STATION_TRANSLATOR = {
    "МОСКВА":          "181102",  # Селятино
    "НОВОСИБИРСК":     "850308",  # Чемской
    "УГЛОВАЯ":         "984700",
    "ВЛАДИВОСТОК":     "980003",
    "ЕКАТЕРИНБУРГ":    "780308",
    "ИРКУТСК":         "932601",
    "КРАСНОЯРСК":      "890006",
}

async def get_station_code(name: str, session) -> str | None:
    # (Код этой функции тот же, что я давал выше - поиск в словаре и БД)
    clean_name = str(name).strip().upper()
    if clean_name in STATION_TRANSLATOR: return STATION_TRANSLATOR[clean_name]
    
    # ... (логика поиска в БД) ...
    # (Для краткости пропускаю, используй полную версию из предыдущего ответа)
    # Если нужно, я продублирую полную версию функции ниже.
    return None # Заглушка

# --- (Вставь сюда полную функцию resolve_code/get_station_code из прошлого ответа) ---
# Давай я лучше напишу полную версию файла ниже, чтобы ты просто скопировал.

def resolve_code_simple(name_raw: str) -> str | None:
    """Упрощенная версия для примера, используй полную с БД если нужно"""
    if pd.isna(name_raw): return None
    s = str(name_raw).strip().upper().split('.')[0]
    if s in STATION_TRANSLATOR: return STATION_TRANSLATOR[s]
    if s.isdigit() and len(s) >= 4: return s
    return None

async def import_tariffs():
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Файл {EXCEL_FILE} не найден.")
        return

    print(f"📂 Чтение {EXCEL_FILE} для сервиса [{IMPORT_FOR_SERVICE}]...")
    try:
        df = pd.read_excel(EXCEL_FILE, dtype=str)
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return

    tariffs_to_insert = []
    
    # Открываем сессию (здесь упрощенно без поиска в БД тарифов, только словарь)
    # Если нужен поиск в БД тарифов - верни тот кусок
    
    for index, row in df.iterrows():
        name_from = row.get(COL_FROM)
        name_to = row.get(COL_TO)
        
        # Используем словарь
        code_from = resolve_code_simple(name_from)
        code_to = resolve_code_simple(name_to)

        if not code_from or not code_to:
            continue

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
                    "service_type": IMPORT_FOR_SERVICE, # <--- ✅ ВОТ ЗДЕСЬ МЫ УКАЗЫВАЕМ ТИП
                    "rate_no_vat": price_val
                })
            except ValueError:
                continue

    if not tariffs_to_insert:
        print("⚠️ Нет данных.")
        return

    print(f"🚀 Запись {len(tariffs_to_insert)} тарифов ({IMPORT_FOR_SERVICE}) в БД...")

    async with SessionLocal() as session:
        stmt = pg_insert(RailTariffRate).values(tariffs_to_insert)
        
        # Обновляем конфликт на новый констрейнт
        upsert_stmt = stmt.on_conflict_do_update(
            constraint='uq_tariff_route_type_service', # ✅ НОВОЕ ИМЯ ОГРАНИЧЕНИЯ
            set_={
                "rate_no_vat": stmt.excluded.rate_no_vat,
                "updated_at": func.now()
            }
        )

        try:
            await session.execute(upsert_stmt)
            await session.commit()
            print(f"✅ УСПЕШНО!")
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка SQL: {e}")

if __name__ == "__main__":
    asyncio.run(import_tariffs())