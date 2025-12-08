import pandas as pd
import logging
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты моделей и сессий
from models_finance import RailTariffRate, ServiceType
from services.tariff_service import TariffStation
from db import TariffSessionLocal

logger = logging.getLogger(__name__)

# Константы колонок Excel (можно адаптировать)
COL_FROM = 'station_from'
COL_TO = 'station_to'
COL_SERVICE = 'service_type' # TRAIN или SINGLE

# Маппинг колонок с ценами из Excel в типы контейнеров БД
RATE_COLUMNS_MAP = {
    'rate_20_ref':   '20_REF',
    'rate_20_heavy': '20_HEAVY',
    'rate_20_extra': '20_EXTRA',
    'rate_40_std':   '40_STD',
    'rate_40_heavy': '40_HEAVY',
    'rate_40_hc':    '40_HC'
}

async def find_station_code_by_name(name: str, session: AsyncSession) -> str | None:
    """
    Ищет код станции в таблице tariff_stations по точному или частичному совпадению имени.
    """
    if not name: return None
    clean_name = name.strip().lower()
    
    # 1. Попытка точного поиска
    stmt = select(TariffStation.code).where(func.lower(TariffStation.name) == clean_name)
    result = await session.execute(stmt)
    code = result.scalar_one_or_none()
    
    if code: return code

    # 2. Попытка поиска по началу строки (например, "Москва" -> "Москва-Товарная...")
    # Берем первый результат, но это может быть рискованно, лучше точное совпадение
    stmt_like = select(TariffStation.code).where(TariffStation.name.ilike(f"{clean_name}%")).limit(1)
    result_like = await session.execute(stmt_like)
    return result_like.scalar_one_or_none()

async def process_tariff_import(file_content: bytes, main_db: AsyncSession) -> dict:
    """
    Обрабатывает Excel файл и пишет тарифы в БД.
    """
    stats = {"total_rows": 0, "inserted": 0, "errors": [], "stations_found": set()}
    
    try:
        df = pd.read_excel(file_content, dtype=str)
        # Приводим заголовки к нижнему регистру для надежности
        df.columns = df.columns.str.strip().str.lower()
        
        # Проверка обязательных колонок (адаптируйте под ваш Excel)
        required_cols = ['station_from', 'station_to'] 
        if not all(col in df.columns for col in required_cols):
            return {"error": f"В файле нет обязательных колонок: {required_cols}"}

        tariffs_to_upsert = []
        
        # Используем сессию тарифов для поиска кодов
        async with TariffSessionLocal() as tariff_session:
            
            for index, row in df.iterrows():
                stats["total_rows"] += 1
                try:
                    name_from = str(row.get('station_from', '')).strip()
                    name_to = str(row.get('station_to', '')).strip()
                    
                    if not name_from or not name_to:
                        continue

                    # 1. Поиск кодов в БД (вместо STATION_TRANSLATOR)
                    code_from = await find_station_code_by_name(name_from, tariff_session)
                    code_to = await find_station_code_by_name(name_to, tariff_session)

                    if not code_from:
                        stats["errors"].append(f"Строка {index+2}: Не найдена станция отправления '{name_from}'")
                        continue
                    if not code_to:
                        stats["errors"].append(f"Строка {index+2}: Не найдена станция назначения '{name_to}'")
                        continue
                    
                    stats["stations_found"].add(f"{name_from}({code_from})")
                    stats["stations_found"].add(f"{name_to}({code_to})")

                    # 2. Определение сервиса (TRAIN/SINGLE)
                    raw_service = str(row.get('service_type', 'TRAIN')).strip().upper()
                    service_type = 'SINGLE' if 'SINGLE' in raw_service or 'ОДИН' in raw_service else 'TRAIN'

                    # 3. Сбор цен по колонкам
                    for excel_col, db_type in RATE_COLUMNS_MAP.items():
                        if excel_col in df.columns:
                            raw_price = row.get(excel_col)
                            if pd.isna(raw_price): continue
                            
                            try:
                                price_val = float(str(raw_price).replace(' ', '').replace(',', '.'))
                                if price_val > 0:
                                    tariffs_to_upsert.append({
                                        "station_from_code": code_from,
                                        "station_to_code": code_to,
                                        "container_type": db_type,
                                        "service_type": service_type,
                                        "rate_no_vat": price_val
                                    })
                            except ValueError:
                                pass

                except Exception as row_e:
                    stats["errors"].append(f"Строка {index+2}: Ошибка обработки - {row_e}")

        # 4. Массовая вставка (Upsert) в основную БД
        if tariffs_to_upsert:
            stmt = pg_insert(RailTariffRate).values(tariffs_to_upsert)
            
            upsert_stmt = stmt.on_conflict_do_update(
                constraint='uq_tariff_route_type_service', # Убедитесь, что это имя совпадает с миграцией
                set_={
                    "rate_no_vat": stmt.excluded.rate_no_vat,
                    "updated_at": func.now()
                }
            )
            await main_db.execute(upsert_stmt)
            await main_db.commit()
            stats["inserted"] = len(tariffs_to_upsert)
        
        return stats

    except Exception as e:
        logger.error(f"Global import error: {e}", exc_info=True)
        return {"error": str(e)}