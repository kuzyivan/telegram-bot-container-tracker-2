import pandas as pd
import logging
import re
from io import BytesIO  # <--- Добавлено для исправления Warning
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты моделей и сессий
from models_finance import RailTariffRate, ServiceType
from services.tariff_service import TariffStation
from db import TariffSessionLocal

logger = logging.getLogger(__name__)

# Маппинг колонок с ценами из Excel в типы контейнеров БД
# Ключ: Название колонки в Excel (в нижнем регистре), Значение: Значение в БД
RATE_COLUMNS_MAP = {
    'rate_20_ref':   '20_REF',
    'rate_20_heavy': '20_HEAVY',
    'rate_20_extra': '20_EXTRA',
    'rate_20_std':   '20_STD',
    'rate_40_std':   '40_STD',
    'rate_40_heavy': '40_HEAVY',
    'rate_40_hc':    '40_HC'
}

def normalize_name(name: str) -> str:
    """Убирает лишние пробелы и приводит к нижнему регистру для поиска."""
    if not isinstance(name, str): return ""
    return name.strip().lower()

async def find_station_code_by_name(name: str, session: AsyncSession) -> str | None:
    """
    Ищет код станции в таблице tariff_stations.
    Пытается найти точное совпадение, затем нечеткое.
    """
    clean_name = normalize_name(name)
    if not clean_name: return None
    
    # 1. Попытка точного поиска по имени
    stmt = select(TariffStation.code).where(func.lower(TariffStation.name) == clean_name)
    result = await session.execute(stmt)
    code = result.scalar_one_or_none()
    
    if code: return code

    # 2. Попытка поиска "Начинается с..." (например Excel: "Москва", БД: "Москва-Товарная...")
    # Ограничиваем 1 результатом. Это fallback.
    stmt_like = select(TariffStation.code).where(func.lower(TariffStation.name).like(f"{clean_name}%")).limit(1)
    result_like = await session.execute(stmt_like)
    return result_like.scalar_one_or_none()

async def process_tariff_import(file_content: bytes, main_db: AsyncSession) -> dict:
    """
    Читает Excel файл (через BytesIO) и пишет тарифы в БД.
    """
    stats = {"total_rows": 0, "inserted": 0, "errors": [], "stations_found": set()}
    
    try:
        # Читаем Excel в память через BytesIO, чтобы избежать FutureWarning
        df = pd.read_excel(BytesIO(file_content), dtype=str)
        
        # Приводим заголовки к нижнему регистру и стрипим
        df.columns = df.columns.str.strip().str.lower()
        
        # Проверка наличия колонок Откуда/Куда
        # (Названия колонок в Excel должны быть station_from и station_to или похожие)
        if 'station_from' not in df.columns or 'station_to' not in df.columns:
            # Попробуем найти русские аналоги, если английских нет
            rename_map = {
                'станция отправления': 'station_from',
                'откуда': 'station_from',
                'станция назначения': 'station_to',
                'куда': 'station_to',
                'тип сервиса': 'service_type'
            }
            df.rename(columns=lambda x: rename_map.get(x, x), inplace=True)

        if 'station_from' not in df.columns or 'station_to' not in df.columns:
            return {"error": "Не найдены колонки 'station_from' (Откуда) и 'station_to' (Куда)."}

        tariffs_to_upsert = []
        
        # Открываем сессию к БД справочников (tariff_db) для поиска кодов
        async with TariffSessionLocal() as tariff_session:
            
            for index, row in df.iterrows():
                stats["total_rows"] += 1
                try:
                    name_from = str(row.get('station_from', '')).strip()
                    name_to = str(row.get('station_to', '')).strip()
                    
                    if not name_from or not name_to:
                        continue

                    # 1. Поиск кодов в БД (Динамически!)
                    code_from = await find_station_code_by_name(name_from, tariff_session)
                    code_to = await find_station_code_by_name(name_to, tariff_session)

                    if not code_from:
                        stats["errors"].append(f"Строка {index+2}: Не найдена станция '{name_from}' в справочнике")
                        continue
                    if not code_to:
                        stats["errors"].append(f"Строка {index+2}: Не найдена станция '{name_to}' в справочнике")
                        continue
                    
                    stats["stations_found"].add(f"{name_from}({code_from})")
                    stats["stations_found"].add(f"{name_to}({code_to})")

                    # 2. Определение сервиса (TRAIN/SINGLE)
                    # Если колонки нет, по умолчанию TRAIN (Контейнерный поезд)
                    raw_service = str(row.get('service_type', 'TRAIN')).strip().upper()
                    
                    # Логика определения: если в ячейке есть "SINGLE" или "ВАГОН" -> SINGLE, иначе TRAIN
                    if 'SINGLE' in raw_service or 'ВАГОН' in raw_service or 'ОДИНОЧ' in raw_service:
                        service_type = ServiceType.SINGLE
                    else:
                        service_type = ServiceType.TRAIN

                    # 3. Сбор цен по колонкам
                    for excel_col, db_type in RATE_COLUMNS_MAP.items():
                        # Ищем колонку в df (она уже в lower case)
                        if excel_col in df.columns:
                            raw_price = row.get(excel_col)
                            if pd.isna(raw_price) or str(raw_price).strip() == '': continue
                            
                            try:
                                # Очистка цены от пробелов и замена запятой
                                price_clean = str(raw_price).replace(' ', '').replace(',', '.').replace('\xa0', '')
                                price_val = float(price_clean)
                                
                                if price_val > 0:
                                    tariffs_to_upsert.append({
                                        "station_from_code": code_from,
                                        "station_to_code": code_to,
                                        "container_type": db_type,
                                        "service_type": service_type,
                                        "rate_no_vat": price_val
                                    })
                            except ValueError:
                                # Если цена не число, пропускаем
                                pass

                except Exception as row_e:
                    stats["errors"].append(f"Строка {index+2}: Критическая ошибка - {row_e}")

        # 4. Массовая вставка (Upsert) в основную БД (main_db)
        if tariffs_to_upsert:
            stmt = pg_insert(RailTariffRate).values(tariffs_to_upsert)
            
            # Обновляем цену, если запись уже есть
            upsert_stmt = stmt.on_conflict_do_update(
                constraint='uq_tariff_route_type_service', # Имя констрейнта из миграции
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
        logger.error(f"Import service error: {e}", exc_info=True)
        return {"error": str(e)}