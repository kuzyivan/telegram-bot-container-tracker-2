# services/tariff_service.py
import asyncio
import re
from sqlalchemy import select, ARRAY, exc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from logger import get_logger

# --- 1. Импортируем новую сессию для тарифов ---
from db import TariffSessionLocal 

logger = get_logger(__name__) 

# --- 2. Определяем модели (копия из мигратора) ---
class TariffBase(DeclarativeBase):
    pass

class TariffStation(TariffBase):
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    # --- 🐞 ИСПРАВЛЕНИЕ: name НЕ уникально ---
    name: Mapped[str] = mapped_column(String, index=True)
    # --- 🐞 ИСПРАВЛЕНИЕ: code УНИКАЛЕН ---
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True)
    operations: Mapped[str | None] = mapped_column(String)
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
    transit_points: Mapped[list[dict] | None] = mapped_column(ARRAY(String))

class TariffMatrix(TariffBase):
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

# --- 3. Вспомогательные функции (асинхронные) ---

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

# --- 🐞 ИСПРАВЛЕНИЕ: Логика 1-в-1 как в zdtarif_bot/core/data_parser.py 🐞 ---
async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    """
    Асинхронно ищет станцию в новой базе тарифов.
    Сначала ищет станцию с пометкой 'ТП', если не находит - берет первую.
    """
    cleaned_name = _normalize_station_name_for_db(station_name)
    
    # 1. Ищем ВСЕ станции, содержащие имя (как str.contains)
    stmt = select(TariffStation).where(TariffStation.name.ilike(f"%{cleaned_name}%"))
    
    result = await session.execute(stmt)
    all_stations = result.scalars().all()

    if not all_stations:
        return None # Совсем ничего не нашли

    # 2. Ищем "идеальное" совпадение - станцию с пометкой 'ТП'
    tp_station = None
    for station in all_stations:
        if station.operations and 'ТП' in station.operations:
            tp_station = station
            break # Нашли!
    
    # 3. Если не нашли ТП, берем первую попавшуюся (как делал iloc[0])
    if not tp_station:
        tp_station = all_stations[0]
        
    # 4. Логгируем, если использовали неточный поиск
    if tp_station.name.lower() != cleaned_name.lower():
        logger.warning(f"[Tariff] Станция '{cleaned_name}' не найдена. Используется {tp_station.name}")

    return {
        'station_name': tp_station.name,
        'station_code': tp_station.code,
        'operations': tp_station.operations,
        'transit_points': _parse_transit_points_from_db(tp_station.transit_points)
    }
# --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

async def _get_matrix_distance_from_db(tp_a_name: str, tp_b_name: str, session: AsyncSession) -> int | None:
    """
    Асинхронно ищет расстояние между двумя ТП в матрице.
    """
    
    # --- 🐞 ИСПРАВЛЕНИЕ: Имитируем .split(' (')[0] из zdtarif_bot 🐞 ---
    # Очищаем имена ТП (например, "Инская (83 З-СИБ)" -> "Инская")
    tp_a_clean = tp_a_name.split(' (')[0]
    tp_b_clean = tp_b_name.split(' (')[0]
    
    # Ищем, чтобы НАЧИНАЛОСЬ с этого имени (имитация str.contains)
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_a_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_b_clean}%")
    ).limit(1)
    
    # Ищем B -> A
    stmt_ba = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_b_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_a_clean}%")
    ).limit(1)
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

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

# --- 4. Основная функция (полностью асинхронная) ---

async def get_tariff_distance(from_station_name: str, to_station_name: str) -> int | None:
    """
    Рассчитывает тарифное расстояние, используя АСИНХРОННЫЕ запросы
    к специальной базе данных тарифов.
    """
    if not TariffSessionLocal:
        logger.error("[Tariff] TARIFF_DATABASE_URL не настроен. Расчет невозможен.")
        return None

    if not from_station_name or not to_station_name:
        logger.info(f"[Tariff] Недостаточно данных для расчета: {from_station_name} -> {to_station_name}")
        return None

    try:
        async with TariffSessionLocal() as session:
            
            # 1. Получаем инфо о станциях
            info_a = await _get_station_info_from_db(from_station_name, session)
            info_b = await _get_station_info_from_db(to_station_name, session)

            if not info_a:
                logger.warning(f"[Tariff] Станция '{from_station_name}' не найдена в базе тарифов.")
                return None
            if not info_b:
                logger.warning(f"[Tariff] Станция '{to_station_name}' не найдена в базе тарифов.")
                return None
            
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return 0

            # --- 🐞 ИСПРАВЛЕНИЕ: Логика 1-в-1 как в zdtarif_bot/core/calculator.py 🐞 ---
            
            # 2. Логика определения ТП для Станции А
            tps_a = []
            operations_a = info_a.get('operations') or ""
            transit_points_a = info_a.get('transit_points', [])
            
            if 'ТП' in operations_a:
                tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            elif transit_points_a:
                tps_a = transit_points_a
            else:
                tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            
            # 3. Логика определения ТП для Станции Б
            tps_b = []
            operations_b = info_b.get('operations') or ""
            transit_points_b = info_b.get('transit_points', [])
            
            if 'ТП' in operations_b:
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]
            elif transit_points_b:
                tps_b = transit_points_b
            else:
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]
            
            # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

            min_total_distance = float('inf')
            route_found = False

            # Перебираем все комбинации ТП
            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    # 4. Асинхронный запрос к матрице
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    
                    if transit_dist is not None:
                        total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            route_found = True

            if route_found:
                distance_int = int(min_total_distance)
                logger.info(f"✅ [Tariff] Расстояние получено (SQL): {from_station_name} -> {to_station_name} = {distance_int} км.")
                return distance_int
            else:
                logger.info(f"[Tariff] Маршрут (ТП) не найден в матрице для {from_station_name} -> {to_station_name}.")
                return None

    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при SQL-расчете расстояния: {e}", exc_info=True)
        return None