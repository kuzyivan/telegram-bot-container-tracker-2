# services/tariff_service.py
import asyncio
import re
# 1. ИМПОРТИРУЕМ func
from sqlalchemy import select, ARRAY, exc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from logger import get_logger

# --- Импортируем новую сессию для тарифов ---
from db import TariffSessionLocal 

logger = get_logger(__name__) 

# --- Определяем модели (копия из мигратора) ---
class TariffBase(DeclarativeBase):
    pass

class TariffStation(TariffBase):
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True)
    operations: Mapped[str | None] = mapped_column(String)
    railway: Mapped[str | None] = mapped_column(String)
    
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String))

class TariffMatrix(TariffBase):
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

# --- Вспомогательные функции (асинхронные) ---

def _normalize_station_name_for_db(name: str) -> str:
    """
    Очищает имя станции от кода, как это было в zdtarif_bot.
    Пример: 'Селятино (181102)' -> 'Селятино'
    """
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    return cleaned_name if cleaned_name else name.strip()

def _parse_transit_points_from_db(tp_strings: list[str]) -> list[dict]:
    """
    Преобразует строки "КОД:ИМЯ:ДИСТАНЦИЯ" обратно в словари.
    """
    transit_points = []
    if not tp_strings:
        return []
        
    for tp_str in tp_strings:
        try:
            parts = tp_str.split(':')
            transit_points.append({
                'code': parts[0],
                'name': parts[1],
                'distance': int(parts[2])
            })
        except Exception:
            continue # Игнорируем некорректную строку
    return transit_points

async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    """
    Асинхронно ищет станцию в новой базе тарифов.
    """
    cleaned_name = _normalize_station_name_for_db(station_name) # Получаем 'ХАБАРОВСК 2'
    
    # 1. Создаем варианты поиска
    search_variants = {cleaned_name}
    
    # 2. Добавляем вариант с римскими цифрами
    if " 2" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 1", " I"))
    
    # 3. Ищем по ЛЮБОМУ из вариантов
    
    # --- ✅ НАЧАЛО ИСПРАВЛЕНИЯ (Регистр + Цифры) ---
    # Преобразуем варианты в нижний регистр
    search_variants_lower = [v.lower() for v in search_variants]
    
    # Ищем, используя func.lower() для нечувствительности к регистру
    stmt = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
    # --- ⛔️ КОНЕЦ ИСПРАВЛЕНИЯ ---

    result = await session.execute(stmt)
    all_stations = result.scalars().all()

    # 4. Если точное совпадение не найдено, возвращаемся к ILIKE как запасной вариант
    if not all_stations:
        # Ищем "хабаровск%" (начинается с), а не "%хабаровск%" (содержит)
        stmt_fallback = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
        result_fallback = await session.execute(stmt_fallback)
        all_stations = result_fallback.scalars().all()

    if not all_stations:
        return None 

    # 5. Ищем "идеальное" совпадение - станцию с пометкой 'ТП'
    tp_station = None
    for station in all_stations:
        if station.operations and 'ТП' in station.operations:
            tp_station = station
            break 
    
    # 6. Если не нашли ТП, берем первую попавшуюся
    if not tp_station:
        tp_station = all_stations[0]
        
    if tp_station.name.lower() != cleaned_name.lower():
        logger.warning(f"[Tariff] Станция '{cleaned_name}' не найдена. Используется {tp_station.name}")

    return {
        'station_name': tp_station.name,
        'station_code': tp_station.code,
        'operations': tp_station.operations,
        'railway': tp_station.railway, 
        'transit_points': _parse_transit_points_from_db(tp_station.transit_points)
    }

async def _get_matrix_distance_from_db(tp_a_name: str, tp_b_name: str, session: AsyncSession) -> int | None:
    """
    Асинхронно ищет расстояние между двумя ТП в матрице.
    """
    tp_a_clean = tp_a_name.split(' (')[0]
    tp_b_clean = tp_b_name.split(' (')[0]
    
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_a_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_b_clean}%")
    ).limit(1)
    
    stmt_ba = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_b_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_a_clean}%")
    ).limit(1)

    try:
        result_ab = await session.execute(stmt_ab)
        distance = result_ab.scalar_one_or_none()
        if distance is not None:
            return distance

        result_ba = await session.execute(stmt_ba)
        distance_ba = result_ba.scalar_one_or_none()
        if distance_ba is not None:
            return distance_ba
            
    except exc.OperationalError as e:
        logger.error(f"Ошибка подключения к БД тарифов: {e}")
        return None
        
    return None

# --- Основная функция (полностью асинхронная) ---

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> dict | None:
    """
    Рассчитывает тарифное расстояние, используя АСИНХРОННЫЕ запросы
    к специальной базе данных тарифов.
    Возвращает словарь {'distance': int, 'info_a': dict, 'info_b': dict} или None.
    """
    if not TariffSessionLocal:
        logger.error("[Tariff] TARIFF_DATABASE_URL не настроен. Расчет невозможен.")
        return None

    if not from_station_name or not to_station_name:
        logger.info(f"[Tariff] Недостаточно данных для расчета: {from_station_name} -> {to_station_name}")
        return None

    try:
        async with TariffSessionLocal() as session:
            
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)

            if not info_a:
                logger.warning(f"[Tariff] Станция '{from_station_name}' не найдена в базе тарифов.")
                return None
            if not info_b:
                logger.warning(f"[Tariff] Станция '{to_station_name}' не найдена в базе тарифов.")
                return None
            
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {'distance': 0, 'info_a': info_a, 'info_b': info_b}
            
            tps_a = []
            operations_a = info_a.get('operations') or ""
            transit_points_a = info_a.get('transit_points', [])
            
            if 'ТП' in operations_a:
                tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            elif transit_points_a:
                tps_a = transit_points_a
            else:
                tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            
            tps_b = []
            operations_b = info_b.get('operations') or ""
            transit_points_b = info_b.get('transit_points', [])
            
            if 'ТП' in operations_b:
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]
            elif transit_points_b:
                tps_b = transit_points_b
            else:
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]

            min_total_distance = float('inf')
            route_found = False

            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    
                    if transit_dist is not None:
                        total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            route_found = True

            if route_found:
                distance_int = int(min_total_distance)
                logger.info(f"✅ [Tariff] Расстояние получено (SQL): {from_station_name} -> {to_station_name} = {distance_int} км.")
                return {
                    'distance': distance_int,
                    'info_a': info_a,
                    'info_b': info_b
                }
            else:
                logger.info(f"[Tariff] Маршрут (ТП) не найден в матрице для {from_station_name} -> {to_station_name}.")
                return None

    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при SQL-расчете расстояния: {e}", exc_info=True)
        return None


# --- НОВАЯ ФУНКЦИЯ ДЛЯ ПОИСКА СТАНЦИЙ (ШАГ 1) ---
async def find_stations_by_name(station_name: str) -> list[dict]:
    """
    Ищет станции по имени, возвращает список совпадений.
    """
    if not TariffSessionLocal:
        logger.error("[Tariff] TARIFF_DATABASE_URL не настроен. Поиск невозможен.")
        return []

    cleaned_name = _normalize_station_name_for_db(station_name) # Очищает от (кода)
    
    # 1. Создаем варианты поиска (для "Хабаровск 2" -> "Хабаровск II")
    search_variants = {cleaned_name}
    if " 2" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 1", " I"))

    async with TariffSessionLocal() as session:
        # 2. Сначала ищем точные совпадения
        
        # --- ✅ НАЧАЛО ИСПРАВЛЕНИЯ (Регистр + Цифры) ---
        # Преобразуем варианты в нижний регистр
        search_variants_lower = [v.lower() for v in search_variants]
        
        # Ищем, используя func.lower() для нечувствительности к регистру
        stmt_exact = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
        # --- ⛔️ КОНЕЦ ИСПРАВЛЕНИЯ ---
        
        result_exact = await session.execute(stmt_exact)
        all_stations = result_exact.scalars().all()
        
        # 3. Если точных нет, ищем по "начинается с" (Хабаровск -> Хабаровск 1, Хабаровск 2)
        if not all_stations:
            # ILIKE 'хабаровск%' (не '%хабаровск%')
            stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
            result_startswith = await session.execute(stmt_startswith)
            all_stations = result_startswith.scalars().all()

        # 4. Форматируем результат
        station_list = []
        for station in all_stations:
            station_list.append({
                'name': station.name,
                'code': station.code,
                'railway': station.railway
            })
        
        return station_list