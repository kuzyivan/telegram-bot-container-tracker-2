# services/railway_router.py
from typing import Optional, List
from services.osm_service import fetch_station_coords
from services.distance_calculator import haversine_distance, RAILWAY_WINDING_FACTOR
from logger import get_logger

logger = get_logger(__name__)

# --- СПИСОК СТАНЦИЙ МОСКОВСКОГО УЗЛА ---
# Добавьте сюда "чистые" названия других станций по необходимости
MOSCOW_HUB_STATIONS = {
    "СЕЛЯТИНО",
    "ЭЛЕКТРОУГЛИ",
    "БЕЛЫЙ РАСТ",
    "ХОВРИНО",
    "КРЕСТЫ",
    "БЕКАСОВО I",
    "БЕКАСОВО-СОРТИРОВОЧНОЕ"
}

# --- СПРАВОЧНИК МАРШРУТОВ ---
# Теперь ключ - это общее направление, а в списке нет конечной точки.
WAYPOINTS = {
    "УГЛОВАЯ-MOSCOW_HUB": [
        "УГЛОВАЯ",
        "ХАБАРОВСК I",
        "АРХАРА",
        "КРАСНОЯРСК-ВОСТОЧНЫЙ",
        "ЕКАТЕРИНБУРГ-СОРТИРОВОЧНЫЙ",
    ]
}

def _clean_station_name_for_router(station_name: str) -> str:
    """Очищает имя станции от кодов и уточнений для поиска в справочнике."""
    name = station_name.split('(')[0].strip()
    name = name.replace('ЭКСП.', '').strip()
    return name

async def get_distance_via_waypoints(route: List[str], current_station: str) -> Optional[int]:
    """Рассчитывает расстояние по опорным точкам до конца маршрута."""
    try:
        current_idx = route.index(current_station)
    except ValueError:
        logger.warning(f"Текущая станция '{current_station}' не является опорной в маршруте {route}")
        return None

    total_distance = 0
    
    # Суммируем расстояния между оставшимися опорными точками
    for i in range(current_idx, len(route) - 1):
        segment_distance = await calculate_distance_between_two_stations(route[i], route[i+1])
        if segment_distance is None: 
            logger.error(f"Не удалось рассчитать сегмент от {route[i]} до {route[i+1]}")
            return None
        total_distance += segment_distance
        
    return total_distance

async def calculate_distance_between_two_stations(station1: str, station2: str) -> Optional[int]:
    """Вспомогательная функция для расчета расстояния между двумя станциями."""
    coords1 = await fetch_station_coords(station1)
    coords2 = await fetch_station_coords(station2)
    
    if coords1 and coords2:
        direct_distance = haversine_distance(
            coords1['lat'], coords1['lon'],
            coords2['lat'], coords2['lon']
        )
        return int(direct_distance * RAILWAY_WINDING_FACTOR)
    return None

async def get_remaining_distance_on_route(
    start_station: str,
    end_station: str,
    current_station: str
) -> Optional[int]:
    """Главная функция-маршрутизатор."""
    
    clean_start = _clean_station_name_for_router(start_station)
    clean_end = _clean_station_name_for_router(end_station)
    clean_current = _clean_station_name_for_router(current_station)
    
    # 1. Проверяем, является ли станция назначения частью Московского узла
    if clean_end in MOSCOW_HUB_STATIONS:
        route_key = f"{clean_start}-MOSCOW_HUB"
        
        # 2. Проверяем, есть ли для этого направления базовый маршрут
        if route_key in WAYPOINTS:
            logger.info(f"Направление {route_key} определено. Динамически строю маршрут до '{clean_end}'.")
            
            # 3. Динамически создаем полный маршрут
            base_route = WAYPOINTS[route_key]
            full_route = base_route + [clean_end] # Добавляем реальную конечную станцию
            
            distance = await get_distance_via_waypoints(full_route, clean_current)
            if distance is not None:
                logger.info(f"Расстояние по опорным точкам до '{clean_end}': {distance} км.")
                return distance

    # 4. Если маршрут не определен или станция не опорная, используем прямой расчет
    logger.warning(f"Маршрут от '{clean_start}' до '{clean_end}' не найден в справочнике или текущая станция не является опорной. Используется прямой расчет.")
    return await calculate_distance_between_two_stations(clean_current, clean_end)