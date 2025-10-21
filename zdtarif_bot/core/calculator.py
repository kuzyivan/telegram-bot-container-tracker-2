# core/calculator.py

import pandas as pd
import itertools
import logging
import re # <-- НОВЫЙ ИМПОРТ RE
from .data_parser import find_station_info, normalize_station_name

logger = logging.getLogger(__name__)

def get_transit_distance(tp1_name: str, tp2_name: str, matrices: dict):
    """Ищет расстояние между двумя ТП в предоставленных матрицах."""
    tp1_name = tp1_name.strip()
    tp2_name = tp2_name.strip()

    if normalize_station_name(tp1_name) == normalize_station_name(tp2_name):
        return 0

    for matrix_name, matrix_df in matrices.items():
        # Ищем кандидатов по частичному совпадению
        row_candidates = matrix_df.index[matrix_df.index.str.contains(tp1_name, case=False, na=False)]
        col_candidates = matrix_df.columns[matrix_df.columns.str.contains(tp2_name, case=False, na=False)]
        
        if not row_candidates.empty and not col_candidates.empty:
            try:
                distance_val = matrix_df.loc[row_candidates[0], col_candidates[0]]
                if isinstance(distance_val, pd.Series):
                    distance_val = distance_val.iloc[0]
                
                if pd.notna(distance_val):
                    return int(distance_val)
            except (KeyError, IndexError):
                pass
        
        # Обратный поиск
        row_candidates_rev = matrix_df.index[matrix_df.index.str.contains(tp2_name, case=False, na=False)]
        col_candidates_rev = matrix_df.columns[matrix_df.columns.str.contains(tp1_name, case=False, na=False)]
        
        if not row_candidates_rev.empty and not col_candidates_rev.empty:
            try:
                distance_val_rev = matrix_df.loc[row_candidates_rev[0], col_candidates_rev[0]]
                if isinstance(distance_val_rev, pd.Series):
                    distance_val_rev = distance_val_rev.iloc[0]

                if pd.notna(distance_val_rev):
                    return int(distance_val_rev)
            except (KeyError, IndexError):
                pass
                
    return None

def calculate_distance(station_a_name: str, station_b_name: str, stations_df: pd.DataFrame, matrices: dict):
    """Основная функция для расчета расстояния."""
    
    # ✅ ИСПРАВЛЕНИЕ: Удаляем код станции в скобках, прежде чем искать его в справочнике 2-РП
    cleaned_a_name = re.sub(r'\s*\([^)]*\)', '', station_a_name).strip()
    cleaned_b_name = re.sub(r'\s*\([^)]*\)', '', station_b_name).strip()

    info_a = find_station_info(cleaned_a_name, stations_df)
    info_b = find_station_info(cleaned_b_name, stations_df)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    if not info_a:
        return {'status': 'error', 'message': f'Станция "{station_a_name}" не найдена.'}
    if not info_b:
        return {'status': 'error', 'message': f'Станция "{station_b_name}" не найдена.'}
        
    if info_a['station_name'].lower() == info_b['station_name'].lower():
        return {'status': 'success', 'route': {'from': info_a['station_name'], 'to': info_b['station_name'], 'total_distance': 0, 'is_same_station': True}}

    def get_effective_tps(station_info):
        """Определяет ТП. Если станция сама является ТП, использует только ее."""
        tps = station_info['transit_points']
        station_name = station_info['station_name']
        
        self_as_tp = next((tp for tp in tps if tp['distance'] == 0 and normalize_station_name(tp['name']) == normalize_station_name(station_name)), None)

        if self_as_tp:
            logger.info(f"Станция '{station_name}' сама является ТП. Используется только: {self_as_tp}")
            return [self_as_tp]
        elif tps:
            logger.info(f"Станция '{station_name}' не является ТП, используются все доступные ТП: {tps}")
            return tps
        else:
            logger.info(f"Для станции '{station_name}' ТП не найдены, используется сама станция как ТП.")
            return [{'name': station_name, 'distance': 0}]
            
    effective_tps_a = get_effective_tps(info_a)
    effective_tps_b = get_effective_tps(info_b)
    
    min_total_distance = float('inf')
    best_route = None
    
    for tp_a, tp_b in itertools.product(effective_tps_a, effective_tps_b):
        
        transit_dist = get_transit_distance(tp_a['name'], tp_b['name'], matrices)
        
        if transit_dist is not None:
            total_distance = tp_a['distance'] + transit_dist + tp_b['distance']
            
            if total_distance < min_total_distance:
                min_total_distance = total_distance
                best_route = {
                    'from': station_a_name, 'to': station_b_name,
                    'distance_a_to_tpa': tp_a['distance'], 'tpa_name': tp_a['name'],
                    'distance_tpa_to_tpb': transit_dist, 'tpb_name': tp_b['name'],
                    'distance_tpb_to_b': tp_b['distance'], 'total_distance': total_distance,
                    'is_same_station': False
                }
                
    if best_route:
        return {'status': 'success', 'route': best_route}
    else:
        return {'status': 'error', 'message': 'Не удалось найти расстояние между транзитными пунктами в матрицах 3-1 и 3-2 Рос.'}