# zdtarif_bot/rail_calculator.py
import os
import sys
import logging

# --- Добавляем путь к ПАПКЕ ПРОЕКТА ---
current_file_path = os.path.abspath(__file__)
zdtarif_bot_dir = os.path.dirname(current_file_path)
project_root_dir = os.path.dirname(zdtarif_bot_dir)
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)

# ✅ Импортируем нужные ФУНКЦИИ
from zdtarif_bot.core.data_loader import load_kniga_2_rp, load_kniga_3_matrices
# ✅ Импортируем функцию calculate_distance
from zdtarif_bot.core.calculator import calculate_distance

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Глобальные переменные для хранения загруженных данных ---
stations_data = None
distance_matrices_data = None
initialization_error = None

try:
    data_dir_path = os.path.join(zdtarif_bot_dir, 'data')
    logger.info(f"Загрузка данных станций и матриц из: {data_dir_path}")

    stations_data = load_kniga_2_rp(data_dir_path)
    distance_matrices_data = load_kniga_3_matrices(data_dir_path)

    if stations_data is None or not distance_matrices_data:
        initialization_error = "Не удалось загрузить данные станций или матриц."
        logger.error(f"💥 CRITICAL: {initialization_error}")
    else:
        logger.info("✅ Данные станций и матриц успешно загружены.")

except FileNotFoundError as e:
    initialization_error = f"Папка данных или файл не найдены: {e}"
    logger.error(f"💥 CRITICAL: {initialization_error}", exc_info=True)
    logger.error(f"   Проверялся путь: {data_dir_path}")
except Exception as e:
    initialization_error = f"Ошибка при загрузке данных: {e}"
    logger.error(f"💥 CRITICAL: {initialization_error}", exc_info=True)


# --- Main Function for External Use ---
# ✅ ИСПРАВЛЕНО: Принимаем station_name_1/2, как ожидается в services/tariff_service.py
def get_distance_sync(station_name_1: str, station_name_2: str) -> int | None:
    """
    Рассчитывает тарифное расстояние, используя загруженные данные и функцию calculate_distance.
    
    ПРИМЕЧАНИЕ: Принимает ПОЛНЫЕ НАЗВАНИЯ СТАНЦИЙ, которые включают код (например, 'СЕЛЯТИНО (181102)').
    """
    if initialization_error:
        logger.error(f"❌ Данные не были загружены ({initialization_error}), расчет невозможен.")
        return None
    if stations_data is None or not distance_matrices_data:
         logger.error("❌ Данные станций или матриц не загружены, расчет невозможен.")
         return None

    if not station_name_1 or not station_name_2:
        logger.warning("Получено пустое имя станции. Расчет невозможен.")
        return None

    try:
        # ✅ ИСПРАВЛЕНИЕ: Вызываем calculate_distance с позиционными аргументами,
        # которые соответствуют station_a_name и station_b_name в zdtarif_bot/core/calculator.py
        result = calculate_distance(
            station_name_1, # <--- ПЕРВЫЙ ПОЗИЦИОННЫЙ (соответствует station_a_name в ядре)
            station_name_2, # <--- ВТОРОЙ ПОЗИЦИОННЫЙ (соответствует station_b_name в ядре)
            stations_df=stations_data, 
            matrices=distance_matrices_data 
        )

        if result and result['status'] == 'success':
            distance_int = result['route']['total_distance']
            if distance_int > 0:
                logger.debug(f"Расстояние рассчитано: {station_name_1} -> {station_name_2} = {distance_int} км")
                return distance_int
            else:
                logger.info(f"Функция calculate_distance вернула 0 или <0 для {station_name_1} -> {station_name_2}.")
                return 0
        else:
            logger.info(f"Расстояние не найдено функцией calculate_distance для {station_name_1} -> {station_name_2}. Сообщение: {result.get('message') if result else 'Неизвестно'}")
            return None

    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при вызове calculate_distance для {station_name_1}-{station_name_2}: {e}", exc_info=True)
        return None

# --- Example Usage (Optional) ---
if __name__ == '__main__':
    if not initialization_error:
        logger.info("Запуск тестовых расчетов...")
        code1 = "Селятино (181102)" 
        code2 = "Инская (850007)" 
        dist = get_distance_sync(code1, code2)
        # ... остальной тестовый код ...
    else:
        logger.error(f"Невозможно запустить тесты: {initialization_error}")