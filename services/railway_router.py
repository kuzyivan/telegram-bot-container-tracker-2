# services/railway_router.py
from typing import Optional
import re
from services.osm_service import fetch_station_coords, get_canonical_name # Убедимся, что get_canonical_name импортирован
from services.distance_calculator import haversine_distance, RAILWAY_WINDING_FACTOR
from logger import get_logger

logger = get_logger(__name__)

# Убираем старую функцию очистки, будем использовать каноническую из osm_service
# def _clean_station_name(station_name: str) -> str: ...

async def get_remaining_distance_on_route(
    start_station: str,
    end_station: str,
    current_station: str
) -> Optional[int]:
    """
    Простой и надежный расчет расстояния.
    """
    # Используем канонические имена для логирования
    canon_current = get_canonical_name(current_station)
    canon_end = get_canonical_name(end_station)

    logger.info(f"Начинаю прямой расчет расстояния от '{canon_current}' до '{canon_end}'.")
    
    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    # Вызываем fetch_station_coords с двумя одинаковыми аргументами,
    # так как при поиске в реальном времени "имя для поиска" и "оригинал" совпадают.
    current_coords = await fetch_station_coords(current_station, current_station)
    end_coords = await fetch_station_coords(end_station, end_station)
    
    if not current_coords or not end_coords:
        logger.error(f"Не удалось получить координаты для одной из станций: '{canon_current}' или '{canon_end}'.")
        return None

    # Рассчитываем расстояние
    direct_distance = haversine_distance(
        current_coords['lat'], current_coords['lon'],
        end_coords['lat'], end_coords['lon']
    )
    
    estimated_distance = int(direct_distance * RAILWAY_WINDING_FACTOR)
    logger.info(f"Расчетное расстояние по прямой с коэффициентом: {estimated_distance} км.")
    
    return estimated_distance