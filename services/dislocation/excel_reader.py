import pandas as pd
from typing import Optional, List, Dict, Any
from logger import get_logger 
from services.dislocation.constants import COLUMN_MAPPING_RZD_NEW, EXCEL_COLS_AS_STR, STRING_COLS_TO_CONVERT, DT_FORMAT_WITH_TIME, DT_FORMAT_DATE_ONLY
from datetime import datetime

logger = get_logger(__name__)

def _fill_empty_rows_with_previous(df: pd.DataFrame, column_name: str) -> pd.DataFrame:
    """Заполняет пустые значения в указанном столбце предыдущими значениями."""
    # Предполагаем, что pd.DataFrame уже был создан, и Pandas доступен.
    # Это синхронная функция, как и в оригинальном коде.
    df[column_name] = df[column_name].ffill()
    return df

def _process_data_types(row_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводит типы данных в строке к нужным форматам (даты, числа, строки).
    """
    container_number = row_data.get('container_number', 'UNKNOWN')

    # Признак груженого рейса
    if 'is_loaded_trip' in row_data and row_data['is_loaded_trip'] is not None:
        # Конвертируем '1'/'0' или True/False в bool
        if isinstance(row_data['is_loaded_trip'], str):
            row_data['is_loaded_trip'] = row_data['is_loaded_trip'].strip().lower() in ('1', 'true', 'да', 'yes')
        elif isinstance(row_data['is_loaded_trip'], (int, float)):
            row_data['is_loaded_trip'] = bool(row_data['is_loaded_trip'])
    
    # Даты
    for date_col in ['operation_date', 'trip_start_datetime', 'trip_end_datetime', 'delivery_deadline']:
        if date_col in row_data and row_data[date_col] is not None:
            raw_date = row_data[date_col]
            if pd.isna(raw_date):
                row_data[date_col] = None
                continue
            
            # Если raw_date уже datetime (например, если pandas распознал его)
            if isinstance(raw_date, datetime):
                # Удаляем tzinfo, если есть
                if raw_date.tzinfo:
                    row_data[date_col] = raw_date.replace(tzinfo=None)
                continue
            
            try:
                # 1. Попытка парсинга с временем
                py_dt = datetime.strptime(str(raw_date), DT_FORMAT_WITH_TIME)
                row_data[date_col] = py_dt
            except ValueError:
                try:
                    # 2. Попытка парсинга только с датой
                    py_dt = datetime.strptime(str(raw_date), DT_FORMAT_DATE_ONLY)
                    row_data[date_col] = py_dt
                except Exception:
                    try:
                        # 3. Попытка парсинга с помощью pandas.to_datetime
                        py_dt = pd.to_datetime(raw_date, dayfirst=True).to_pydatetime()
                        if py_dt.tzinfo:
                            py_dt = py_dt.replace(tzinfo=None)
                        row_data[date_col] = py_dt
                    except Exception as e_pandas:
                        logger.warning(f"Не удалось распознать дату '{raw_date}' для контейнера {container_number}: {e_pandas}")
                        row_data[date_col] = None

    # Числа (целые)
    for key in ['cargo_weight_kg', 'total_distance', 'distance_traveled', 'km_left']:
        if key in row_data and row_data[key] is not None:
            try:
                # float('12345.0') -> 12345, str('12345') -> 12345
                row_data[key] = int(float(row_data[key]))
            except (ValueError, TypeError):
                row_data[key] = None 
    
    # Строки (удаляем .0)
    for col_name in STRING_COLS_TO_CONVERT:
        if col_name in row_data and row_data[col_name] is not None:
            row_data[col_name] = str(row_data[col_name]).removesuffix('.0')
            
    return row_data


def read_excel_data(filepath: str) -> Optional[List[Dict[str, Any]]]:
    """
    Считывает данные из .xlsx файла дислокации от РЖД, приводит их к общему формату 
    и возвращает список словарей.
    """
    logger.info(f"[ExcelReader] Чтение файла дислокации: {filepath}")
    
    try:
        dtype_map = {col: str for col in EXCEL_COLS_AS_STR}
        
        # skiprows=3, header=0 - стандартный формат РЖД
        df = pd.read_excel(filepath, skiprows=3, header=0, engine='openpyxl', dtype=dtype_map)
        
        # Проверка формата
        if 'Идентификатор отправки' not in df.columns and 'Тип контейнера' not in df.columns:
            logger.error(f"[ExcelReader] Файл {filepath} не похож на новый формат (нет маркер-столбцов).")
            return None
            
        logger.info(f"[ExcelReader] Обнаружен НОВЫЙ формат дислокации (РЖД).")
            
        valid_columns = [col for col in df.columns if col in COLUMN_MAPPING_RZD_NEW]
        if not valid_columns:
            logger.error("[ExcelReader] Новый формат распознан, но не найдено столбцов из COLUMN_MAPPING_RZD_NEW.")
            return None
        
        df = df[valid_columns]
        df.rename(columns=COLUMN_MAPPING_RZD_NEW, inplace=True)
            
        if 'container_number' in df.columns:
            # Заполняем пустые номера контейнеров предыдущими
            df = _fill_empty_rows_with_previous(df, 'container_number')
        else:
            logger.error("[ExcelReader] Критическая ошибка: 'container_number' не найден в файле.")
            return None

        # Превращаем DataFrame в список словарей и обрабатываем типы
        data_rows = []
        for index, row in df.iterrows():
            # Игнорируем ошибку Pylance, связанную с to_dict() после .where(..., None)
            row_data = row.where(pd.notna(row), None).to_dict() # type: ignore
            
            # Исключаем строки без номера контейнера
            if not row_data.get('container_number'):
                continue
                
            data_rows.append(_process_data_types(row_data))
        
        logger.info(f"[ExcelReader] Успешно прочитано и обработано {len(data_rows)} записей.")
        return data_rows
            
    except Exception as e:
        logger.error(f"[ExcelReader] Ошибка при чтении Excel файла {filepath}: {e}", exc_info=True)
        return None
