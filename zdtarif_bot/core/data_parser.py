# core/data_parser.py

import pandas as pd
import re

def normalize_station_name(name: str) -> str:
    """
    Приводит название станции к единому, 'нормализованному' виду для гибкого поиска.
    Удаляет пробелы, дефисы, приводит к нижнему регистру и заменяет римские цифры.
    Пример: "Кунцево-II" -> "кунцево2"
    """
    if not isinstance(name, str):
        return ""
    
    # 1. Приводим к нижнему регистру
    normalized = name.lower()
    
    # 2. Заменяем римские цифры на арабские (до 10)
    # Порядок важен: от больших к меньшим, чтобы 'viii' не стал 'v' + 'iii'
    # Эта версия более агрессивна и заменяет римские цифры везде, где они встречаются
    replacements = {
        'x': '10', 'ix': '9', 'viii': '8', 'vii': '7', 'vi': '6', 
        'v': '5', 'iv': '4', 'iii': '3', 'ii': '2', 'i': '1'
    }
    for roman, arabic in replacements.items():
        normalized = normalized.replace(roman, arabic)
        
    # 3. Удаляем все, что НЕ является буквой или цифрой (включая пробелы, дефисы и т.д.)
    # Это финальный шаг, который приводит все к чистому буквенно-цифровому виду.
    normalized = re.sub(r'[^а-яa-z0-9]', '', normalized)
    
    return normalized

def parse_transit_points(tp_string: str):
    """
    Вспомогательная функция для разбора строки с транзитными пунктами.
    """
    if not isinstance(tp_string, str) or not tp_string:
        return []
        
    pattern = re.compile(r'(\d{6})\s(.*?)\s-\s(\d+)км')
    matches = pattern.findall(tp_string)
    
    transit_points = []
    for match in matches:
        transit_points.append({
            'code': match[0],
            'name': match[1].strip(),
            'distance': int(match[2])
        })
        
    return transit_points

def search_station_names(partial_name: str, stations_df: pd.DataFrame, limit: int = 5):
    """
    Ищет станции по частичному совпадению названия и возвращает список.
    """
    if not isinstance(partial_name, str) or not partial_name:
        return []
        
    matches = stations_df[stations_df['station_name'].str.lower().str.contains(partial_name.lower(), na=False)]
    
    return matches['station_name'].drop_duplicates().head(limit).tolist()

def find_station_info(station_name: str, stations_df: pd.DataFrame):
    """
    Ищет станцию по ТОЧНОМУ названию в DataFrame.
    
    ПРИМЕЧАНИЕ: station_name может содержать 'НАЗВАНИЕ (КОД)', поэтому мы его очищаем.
    """
    # 1. Очищаем имя от кода в скобках
    # Это ключевой шаг: удаляем все, что находится после открывающей скобки (включая саму скобку и код)
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', station_name).strip()
    
    # Если очистка привела к пустой строке (что маловероятно), возвращаем исходное имя
    if not cleaned_name:
         cleaned_name = station_name.strip()

    # 2. Ищем по очищенному имени, игнорируя регистр
    # Используем str.strip() для очистки пробелов в DataFrame, чтобы совпадение было точным
    station_data = stations_df[stations_df['station_name'].str.strip().str.lower() == cleaned_name.lower()]
    
    if station_data.empty:
        # Если не нашли по точной очистке, возвращаем None (здесь можно добавить fallback на нормализованное имя,
        # но для тарифного расчета лучше требовать точного совпадения в 2-РП.csv)
        return None
        
    station_series = station_data.iloc[0]
    transit_points = parse_transit_points(station_series['transit_points_raw'])
    
    return {
        'station_name': station_series['station_name'],
        'station_code': station_series['station_code'],
        'transit_points': transit_points
    }