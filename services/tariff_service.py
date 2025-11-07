# services/tariff_service.py
import asyncio
import re
from sqlalchemy import select, ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from logger import get_logger

# --- 1. Импортируем новую сессию для тарифов ---
from db import TariffSessionLocal 

logger = get_logger(__name__) 

# --- 2. Определяем модели (копия из мигратора) ---
# Нам нужно определить модели здесь, чтобы SQLAlchemy знала, с чем работать.
class TariffBase(DeclarativeBase):
    pass

class TariffStation(TariffBase):
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True, unique=True)
    code: Mapped[str] = mapped_column(String(6), index=True)
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

async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    """
    Асинхронно ищет станцию в новой базе тарифов.
    """
    cleaned_name = _normalize_station_name_for_db(station_name)
    
    # Ищем по точному совпадению
    stmt = select(TariffStation).where(TariffStation.name == cleaned_name)
    result = await session.execute(stmt)
    station = result.scalar_one_or_none()
    
    if station:
        return {
            'station_name': station.name,
            'station_code': station.code,
            'transit_points': _parse_transit_points_from_db(station.transit_points)
        }
    
    # --- 🐞 ИСПРАВЛЕНИЕ: Используем ilike(f"%{cleaned_name}%") ---
    # Fallback: Если не нашли, ищем по частичному совпадению (как в zdtarif_bot)
    # Используем ilike для регистронезависимого поиска "содержит"
    stmt_like = select(TariffStation).where(TariffStation.name.ilike(f"%{cleaned_name}%")).limit(1)
    result_like = await session.execute(stmt_like)
    station_like = result_like.scalar_one_or_none()
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

    if station_like:
        logger.warning(f"[Tariff] Станция '{cleaned_name}' не найдена. Используется {station_like.name} (поиск по '{cleaned_name}')")
        return {
            'station_name': station_like.name,
            'station_code': station_like.code,
            'transit_points': _parse_transit_points_from_db(station_like.transit_points)
        }
        
    return None

async def _get_matrix_distance_from_db(tp_a_name: str, tp_b_name: str, session: AsyncSession) -> int | None:
    """
    Асинхронно ищет расстояние между двумя ТП в матрице.
    """
    # --- 🐞 ИСПРАВЛЕНИЕ: Используем ilike() для нечеткого поиска ---
    # Ищем A -> B
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"%{tp_a_name}%"),
        TariffMatrix.station_b.ilike(f"%{tp_b_name}%")
    ).limit(1)
    result_ab = await session.execute(stmt_ab)
    distance = result_ab.scalar_one_or_none()
    if distance is not None:
        return distance

    # Ищем B -> A
    stmt_ba = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"%{tp_b_name}%"),
        TariffMatrix.station_b.ilike(f"%{tp_a_name}%")
    ).limit(1)
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---
    
    result_ba = await session.execute(stmt_ba)
    distance_ba = result_ba.scalar_one_or_none()
    if distance_ba is not None:
        return distance_ba
        
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
            
            if info_a['station_name'] == info_b['station_name']:
                return 0

            # 2. Логика расчета (такая же, как в zdtarif_bot/core/calculator.py)
            tps_a = info_a.get('transit_points', [])
            tps_b = info_b.get('transit_points', [])
            
            if not tps_a:
                tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            if not tps_b:
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]

            min_total_distance = float('inf')
            route_found = False

            # Перебираем все комбинации ТП
            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    # 3. Асинхронный запрос к матрице
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