# services/railway_router.py
from typing import Optional
from services.osm_service import fetch_station_coords, generate_name_variations
from services.distance_calculator import haversine_distance, RAILWAY_WINDING_FACTOR
from logger import get_logger

logger = get_logger(__name__)

async def _find_station_coords_with_variations(original_name: str) -> Optional[dict]:
    """
    Ищет координаты станции, перебирая все возможные варианты её названия.
    """
    # Генерируем все возможные варианты написания
    name_variations = generate_name_variations(original_name)
    logger.info(f"Для '{original_name}' сгенерированы варианты для поиска: {name_variations}")
    
    # Последовательно пробуем найти по каждому варианту
    for name_variant in name_variations:
        # Передаем вариант для поиска и оригинал для кеширования
        coords = await fetch_station_coords(name_variant, original_name)
        if coords:
            # Если нашли, сразу возвращаем результат
            return coords
            
    # Если ни один вариант не сработал
    return None

async def get_remaining_distance_on_route(
    start_station: str,
    end_station: str,
    current_station: str
) -> Optional[int]:
    """
    Расчет расстояния с использованием "умного" перебора вариантов названий станций.
    """
    logger.info(f"Начинаю прямой расчет расстояния от '{current_station}' до '{end_station}'.")
    
    # Ищем координаты, перебирая все варианты
    current_coords = await _find_station_coords_with_variations(current_station)
    end_coords = await _find_station_coords_with_variations(end_station)
    
    if not current_coords or not end_coords:
        logger.error(f"Не удалось получить координаты для одной из станций: '{current_station}' или '{end_station}'.")
        return None

    # Рассчитываем расстояние
    direct_distance = haversine_distance(
        current_coords['lat'], current_coords['lon'],
        end_coords['lat'], end_coords['lon']
    )
    
    estimated_distance = int(direct_distance * RAILWAY_WINDING_FACTOR)
    logger.info(f"Расчетное расстояние по прямой с коэффициентом: {estimated_distance} км.")
    
    return estimated_distance