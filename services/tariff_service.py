# services/tariff_service.py
import asyncio
import re
from sqlalchemy import select, ARRAY, exc, func, Index, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession
# ✅ ИСПРАВЛЕНИЕ: Импортируем Base и DeclarativeBase для корректного наследования
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer
from logger import get_logger

# --- Импортируем базовый класс Base из db_base ---
# (Предполагаем, что Base определен в db_base.py или импортирован в db.py)
# Если Base действительно определен в db_base.py:
from db_base import Base
# Если Base определен в models.py (через db_base.py)
# from models import Base 

# В целях самодостаточности, используем Base из db_base.py, как предполагает структура проекта
# Если db_base.py недоступен, мы можем объявить его здесь как DeclarativeBase (но это нарушит DRY)

# Для данного контекста, мы переопределим класс Base для локальных моделей, чтобы избежать конфликтов импорта, 
# используя DeclarativeBase, который уже импортируется.
class TariffBase(DeclarativeBase): 
    pass
    
# --- Импортируем новую сессию для тарифов ---
from db import TariffSessionLocal 

logger = get_logger(__name__) 

# --- Определение ORM Моделей для работы с БД тарифов (обновлены для TariffBase) ---

class TariffStation(TariffBase):
    '''
    Таблица для хранения данных из 2-РП.csv.
    '''
    __tablename__ = 'tariff_stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True) 
    code: Mapped[str] = mapped_column(String(6), index=True, unique=True) 
    railway: Mapped[str | None] = mapped_column(String)
    operations: Mapped[str | None] = mapped_column(String)
    # Используем list[str] как Map для данных ТП, см. migrator
    transit_points: Mapped[list[str] | None] = mapped_column(ARRAY(String)) 

    __table_args__ = (
        Index('ix_tariff_stations_name_code', 'name', 'code'),
    )

class TariffMatrix(TariffBase):
    '''
    Таблица для хранения данных из 3-*.csv.
    '''
    __tablename__ = 'tariff_matrix'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_a: Mapped[str] = mapped_column(String, index=True)
    station_b: Mapped[str] = mapped_column(String, index=True)
    distance: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('station_a', 'station_b', name='uq_station_pair'),
    )


# --- Вспомогательные функции (асинхронные) ---

def _normalize_station_name_for_db(name: str) -> str:
    """
    Очищает имя станции от кода и вставляет пробел перед цифрой (например, ТОМСК1 -> ТОМСК 1).
    """
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    
    # Вставляем пробел между буквой и цифрой (если его нет)
    cleaned_name = re.sub(r'([А-ЯЁA-Z])(\d)', r'\1 \2', cleaned_name)
    
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
            continue
    return transit_points

async def _get_station_info_from_db(station_name: str, session: AsyncSession) -> dict | None:
    """
    Асинхронно ищет станцию в базе тарифов.
    """
    cleaned_name = _normalize_station_name_for_db(station_name)
    
    search_variants = {cleaned_name}
    if " 2" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 1", " I"))
    
    search_variants_lower = [v.lower() for v in search_variants]
    
    stmt = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))

    result = await session.execute(stmt)
    all_stations = result.scalars().all()

    if not all_stations:
        stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
        result_fallback = await session.execute(stmt_startswith)
        all_stations = result_fallback.scalars().all()

    if not all_stations:
        return None 

    tp_station = None
    for station in all_stations:
        if station.operations and 'ТП' in station.operations:
            tp_station = station
            break 
    
    if not tp_station:
        tp_station = all_stations[0]
        
    if tp_station.name.lower() != cleaned_name.lower():
        logger.warning(f"[Tariff] Станция '{cleaned_name}' не найдена. Используется {tp_station.name}")

    return {
        'station_name': tp_station.name,
        'station_code': tp_station.code,
        'operations': tp_station.operations,
        'railway': tp_station.railway, 
        'transit_points': _parse_transit_points_from_db(tp_station.transit_points or [])
    }

async def _get_matrix_distance_from_db(tp_a_name: str, tp_b_name: str, session: AsyncSession) -> int | None:
    """
    Асинхронно ищет расстояние между двумя ТП в матрице.
    """
    tp_a_clean = tp_a_name.split(' (')[0].strip()
    tp_b_clean = tp_b_name.split(' (')[0].strip()
    
    # Ищем A -> B
    stmt_ab = select(TariffMatrix.distance).where(
        TariffMatrix.station_a.ilike(f"{tp_a_clean}%"),
        TariffMatrix.station_b.ilike(f"{tp_b_clean}%")
    ).limit(1)
    
    # Ищем B -> A (симметричный маршрут)
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
    Рассчитывает тарифное расстояние.
    Возвращает словарь {'distance': int, 'info_a': dict, 'info_b': dict, 'route_details': dict} или None.
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

            if not info_a or not info_b:
                if not info_a:
                     logger.warning(f"[Tariff] Станция отправления '{from_station_name}' не найдена.")
                if not info_b:
                     logger.warning(f"[Tariff] Станция назначения '{to_station_name}' не найдена.")
                return None
            
            logger.info(f"[Tariff Debug] A Info: Name={info_a.get('station_name')}, TPs={info_a.get('transit_points')}")
            logger.info(f"[Tariff Debug] B Info: Name={info_b.get('station_name')}, TPs={info_b.get('transit_points')}")
            
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                # Станции совпадают
                return {'distance': 0, 'info_a': info_a, 'info_b': info_b, 'route_details': {'tpa_name': info_a['station_name'], 'tpb_name': info_a['station_name'], 'distance_a_to_tpa': 0, 'distance_tpa_to_tpb': 0, 'distance_tpb_to_b': 0}}


            # --- Определение ТП ---
            tps_a = info_a.get('transit_points', [])
            operations_a = info_a.get('operations') or ""
            if not tps_a or ('ТП' in operations_a and not tps_a):
                 tps_a = [{'name': info_a['station_name'], 'distance': 0}]
            
            tps_b = info_b.get('transit_points', [])
            operations_b = info_b.get('operations') or ""
            if not tps_b or ('ТП' in operations_b and not tps_b):
                tps_b = [{'name': info_b['station_name'], 'distance': 0}]
            # --- Конец определения ТП ---


            min_total_distance = float('inf')
            best_route = None 
            route_found = False

            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    # Пропускаем, если ТП совпадают и это не расчет самого себя
                    if tp_a['name'] == tp_b['name']:
                        if tp_a['distance'] + tp_b['distance'] < min_total_distance:
                            min_total_distance = tp_a['distance'] + tp_b['distance']
                            route_found = True
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'],
                                'tpa_name': tp_a['name'],
                                'distance_tpa_to_tpb': 0, 
                                'tpb_name': tp_b['name'],
                                'distance_tpb_to_b': tp_b['distance'],
                            }
                        continue 
                        
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    
                    if transit_dist is not None:
                        total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
                        
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            route_found = True
                            
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'],
                                'tpa_name': tp_a['name'],
                                'distance_tpa_to_tpb': transit_dist,
                                'tpb_name': tp_b['name'],
                                'distance_tpb_to_b': tp_b['distance'],
                            }

            if route_found and best_route is not None:
                distance_int = int(min_total_distance)
                logger.info(f"✅ [Tariff] Расстояние получено (SQL): {from_station_name} -> {to_station_name} = {distance_int} км. ТП: {best_route['tpa_name']} -> {best_route['tpb_name']}")
                
                return {
                    'distance': distance_int,
                    'info_a': info_a,
                    'info_b': info_b,
                    'route_details': best_route 
                }
            else:
                logger.info(f"[Tariff] Маршрут (ТП) не найден в матрице для {from_station_name} -> {to_station_name}.")
                return None

    except Exception as e:
        logger.error(f"❌ [Tariff] Ошибка при SQL-расчете расстояния: {e}", exc_info=True)
        return None


async def find_stations_by_name(station_name: str) -> list[dict]:
    """
    Ищет станции по имени, возвращает список совпадений.
    """
    if not TariffSessionLocal:
        logger.error("[Tariff] TARIFF_DATABASE_URL не настроен. Поиск невозможен.")
        return []

    cleaned_name = _normalize_station_name_for_db(station_name)
    
    search_variants = {cleaned_name}
    if " 2" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 2", " II"))
    if " 1" in cleaned_name:
        search_variants.add(cleaned_name.replace(" 1", " I"))

    async with TariffSessionLocal() as session:
        
        search_variants_lower = [v.lower() for v in search_variants]
        
        stmt_exact = select(TariffStation).where(func.lower(TariffStation.name).in_(search_variants_lower))
        
        result_exact = await session.execute(stmt_exact)
        all_stations = result_exact.scalars().all()
        
        if not all_stations:
            stmt_startswith = select(TariffStation).where(TariffStation.name.ilike(f"{cleaned_name}%"))
            result_startswith = await session.execute(stmt_startswith)
            all_stations = result_startswith.scalars().all()

        station_list = []
        for station in all_stations:
            station_list.append({
                'name': station.name,
                'code': station.code,
                'railway': station.railway
            })
        
        return station_list