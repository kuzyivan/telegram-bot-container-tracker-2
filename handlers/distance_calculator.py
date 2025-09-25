# services/distance_calculator.py
from math import radians, sin, cos, sqrt, atan2
from logger import get_logger

logger = get_logger(__name__)

EARTH_RADIUS_KM = 6371.0
# Коэффициент, учитывающий, что ж/д путь длиннее прямой линии.
# 1.25 означает, что мы считаем путь на 25% длиннее.
# Его можно настраивать для большей точности.
RAILWAY_WINDING_FACTOR = 1.25

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Вычисляет расстояние по прямой в километрах между двумя точками на Земле (формула гаверсинусов).
    """
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = EARTH_RADIUS_KM * c
    return distance