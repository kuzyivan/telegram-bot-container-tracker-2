# zdtarif_bot/rail_calculator.py
import os
import sys 
import logging

# --- Добавляем путь к ПАПКЕ ПРОЕКТА (AtermTrackBot), чтобы Python нашел zdtarif_bot ---
# Определяем путь к текущему файлу
current_file_path = os.path.abspath(__file__)
# Находим папку zdtarif_bot
zdtarif_bot_dir = os.path.dirname(current_file_path)
# Находим корень проекта (папку выше zdtarif_bot)
project_root_dir = os.path.dirname(zdtarif_bot_dir)
# Добавляем корень проекта в sys.path, если его там нет
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)
    # logger.debug(f"Добавлен {project_root_dir} в sys.path") # Для отладки

# ✅ Используем АБСОЛЮТНЫЕ импорты от корня проекта
from zdtarif_bot.core.data_loader import load_kniga_2_rp, load_kniga_3_matrices 
from zdtarif_bot.core.calculator import Calculator 

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global Calculator Initialization ---
calculator = None

try:
    # Путь к 'data' теперь определяется относительно ЭТОГО файла
    data_dir_path = os.path.join(zdtarif_bot_dir, 'data') 
    logger.info(f"Initializing DataLoader with data path: {data_dir_path}")

    stations_df = load_kniga_2_rp(data_dir_path)
    distance_matrices = load_kniga_3_matrices(data_dir_path)

    if stations_df is not None and distance_matrices:
        calculator = Calculator(stations_df, distance_matrices) 
        logger.info("✅ Calculator инициализирован успешно.")
    else:
        logger.error("💥 CRITICAL: Не удалось загрузить данные станций или матриц.")
        calculator = None 

except FileNotFoundError as e:
    logger.error(f"💥 CRITICAL: Папка данных или файл не найдены: {e}", exc_info=True)
    logger.error(f"   Проверялся путь: {data_dir_path}")
    calculator = None 
except Exception as e:
    logger.error(f"💥 CRITICAL: Ошибка при инициализации калькулятора: {e}", exc_info=True)
    calculator = None

# --- Main Function for External Use ---
def get_distance_sync(station_code_1: str, station_code_2: str) -> int | None:
    """
    Рассчитывает тарифное расстояние с помощью инициализированного калькулятора.
    """
    if not calculator: 
        logger.error("❌ Калькулятор не инициализирован, расчет невозможен.")
        return None

    if not station_code_1 or not station_code_2:
        logger.warning("Получен пустой код станции. Расчет невозможен.")
        return None

    try:
        distance = calculator.get_distance(str(station_code_1), str(station_code_2))

        if distance is not None:
            distance_int = int(distance)
            if distance_int > 0:
                logger.debug(f"Расстояние рассчитано: {station_code_1} -> {station_code_2} = {distance_int} км")
                return distance_int
            else:
                logger.info(f"Калькулятор вернул 0 или отрицательное расстояние для {station_code_1} -> {station_code_2}.")
                return None 
        else:
            logger.info(f"Расстояние не найдено калькулятором для {station_code_1} -> {station_code_2}.")
            return None

    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при расчете расстояния для {station_code_1}-{station_code_2}: {e}", exc_info=True)
        return None

# --- Example Usage (Optional) ---
if __name__ == '__main__':
    if calculator:
        pass # Код для тестов           
    else:
        logger.error("Невозможно запустить тесты, так как калькулятор не инициализирован.")