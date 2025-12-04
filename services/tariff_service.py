# services/tariff_service.py
import asyncio
import re
from sqlalchemy import select, exc, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from logger import get_logger

# --- Импортируем модели из центрального файла models.py ---
from models import TariffStation, TariffMatrix, RailwaySection

# --- Импортируем новую сессию для тарифов ---
from db import TariffSessionLocal 

logger = get_logger(__name__) 

# --- Модели ORM теперь в models.py ---


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

async def _find_stations_between(code_a: str, code_b: str, session: AsyncSession) -> list[dict]:
    """
    Ищет в railway_sections сегмент, содержащий обе станции, 
    и возвращает список станций между ними (включая начальную и конечную).
    """
    if code_a == code_b:
        return []

    # Используем JSONB оператор @> (contains) для поиска.
    # Нам нужен массив, который содержит ОБА объекта: {"c": code_a} И {"c": code_b}
    sql = text("""
        SELECT stations_list 
        FROM railway_sections 
        WHERE stations_list @> :json_a::jsonb AND stations_list @> :json_b::jsonb
        LIMIT 1
    """)
    
    json_a = f'[{{"c": "{code_a}"}}]'
    json_b = f'[{{"c": "{code_b}"}}]'
    
    try:
        result = await session.execute(sql, {"json_a": json_a, "json_b": json_b})
        full_list = result.scalar_one_or_none()
        
        if full_list:
            # Нашли полный список станций. Теперь нужно найти индексы и вырезать нужный кусок.
            idx_a = -1
            idx_b = -1
            
            for i, station in enumerate(full_list):
                if station.get('c') == code_a:
                    idx_a = i
                if station.get('c') == code_b:
                    idx_b = i
            
            if idx_a != -1 and idx_b != -1:
                # Определяем правильный порядок и возвращаем срез
                if idx_a < idx_b:
                    return full_list[idx_a : idx_b + 1]
                else:
                    # Если порядок обратный, разворачиваем список
                    return full_list[idx_b : idx_a + 1][::-1]
                    
    except Exception as e:
        logger.error(f"Ошибка поиска детального маршрута для {code_a}-{code_b}: {e}")
        
    return []

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
            
            if info_a['station_name'].lower() == info_b['station_name'].lower():
                return {
                    'distance': 0, 
                    'info_a': info_a, 
                    'info_b': info_b, 
                    'route_details': {
                        'tpa_name': info_a['station_name'], 'tpa_code': info_a['station_code'],
                        'tpb_name': info_a['station_name'], 'tpb_code': info_a['station_code'],
                        'distance_a_to_tpa': 0, 'distance_tpa_to_tpb': 0, 'distance_tpb_to_b': 0,
                        'detailed_path': [info_a['station_name']]
                    }
                }

            # --- Определение ТП ---
            # Если у станции нет ТП, она сама является ТП
            tps_a = info_a.get('transit_points', []) or [{'code': info_a['station_code'], 'name': info_a['station_name'], 'distance': 0}]
            tps_b = info_b.get('transit_points', []) or [{'code': info_b['station_code'], 'name': info_b['station_name'], 'distance': 0}]
            
            min_total_distance = float('inf')
            best_route = None 

            for tp_a in tps_a:
                for tp_b in tps_b:
                    
                    if tp_a['name'] == tp_b['name']:
                        # Расстояние от А до ТП и от ТП до Б
                        total_distance = tp_a['distance'] + tp_b['distance']
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'], 'tpa_name': tp_a['name'], 'tpa_code': tp_a['code'],
                                'distance_tpa_to_tpb': 0, 
                                'tpb_name': tp_b['name'], 'tpb_code': tp_b['code'],
                                'distance_tpb_to_b': tp_b['distance'],
                            }
                        continue 
                        
                    transit_dist = await _get_matrix_distance_from_db(tp_a['name'], tp_b['name'], session)
                    
                    if transit_dist is not None:
                        total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
                        
                        if total_distance < min_total_distance:
                            min_total_distance = total_distance
                            best_route = {
                                'distance_a_to_tpa': tp_a['distance'], 'tpa_name': tp_a['name'], 'tpa_code': tp_a['code'],
                                'distance_tpa_to_tpb': transit_dist,
                                'tpb_name': tp_b['name'], 'tpb_code': tp_b['code'],
                                'distance_tpb_to_b': tp_b['distance'],
                            }

            if best_route:
                distance_int = int(min_total_distance)
                
                # --- 🔥 Сборка детального маршрута ---
                detailed_path = []
                
                # 1. Участок от станции А до ТП А
                segment1 = await _find_stations_between(info_a['station_code'], best_route['tpa_code'], session)
                if segment1:
                    detailed_path.extend([s['n'] for s in segment1])
                else:
                    detailed_path.append(info_a['station_name'])
                    if info_a['station_name'] != best_route['tpa_name']:
                        detailed_path.append(best_route['tpa_name'])

                # 2. Участок между ТП (если они разные)
                if best_route['tpa_code'] != best_route['tpb_code']:
                    # Пытаемся найти прямой путь между ТП
                    segment2 = await _find_stations_between(best_route['tpa_code'], best_route['tpb_code'], session)
                    if segment2:
                        # Добавляем все станции, кроме первой (которая уже есть)
                        detailed_path.extend([s['n'] for s in segment2[1:]])
                    elif best_route['tpb_name'] not in detailed_path:
                         detailed_path.append(best_route['tpb_name'])
                
                # 3. Участок от ТП Б до станции Б
                segment3 = await _find_stations_between(best_route['tpb_code'], info_b['station_code'], session)
                if segment3:
                    # Добавляем все, кроме первой (ТП Б)
                    detailed_path.extend([s['n'] for s in segment3[1:] if s['n'] not in detailed_path])
                elif info_b['station_name'] not in detailed_path:
                    detailed_path.append(info_b['station_name'])
                
                # Удаляем дубликаты, сохраняя порядок
                final_path = list(dict.fromkeys(detailed_path))
                best_route['detailed_path'] = final_path
                # --- 🔥 Конец сборки ---

                logger.info(f"✅ [Tariff] Расстояние: {distance_int} км. Маршрут: {' -> '.join(final_path)}")
                
                return {
                    'distance': distance_int,
                    'info_a': info_a,
                    'info_b': info_b,
                    'route_details': best_route 
                }
            else:
                logger.warning(f"[Tariff] Маршрут (ТП) не найден в матрице для {from_station_name} -> {to_station_name}.")
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