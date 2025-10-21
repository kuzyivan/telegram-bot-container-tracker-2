# rail_calculator.py (ФИНАЛЬНАЯ ВЕРСИЯ тестового скрипта перед коммитом)

import os
# Импортируем функции из наших новых модулей
from core.data_loader import load_kniga_2_rp, load_kniga_3_matrices
from core.data_parser import search_station_names, find_station_info
from core.calculator import calculate_distance

# --- Константы и пути ---
DATA_DIR = './data' 

# --- Главный блок для запуска и тестирования ---
if __name__ == '__main__':
    print("--- 1. Загрузка данных для тестирования ---")
    df_stations = load_kniga_2_rp(DATA_DIR)
    transit_matrices = load_kniga_3_matrices(DATA_DIR)
    print("\n--- Загрузка завершена! ---\n")

    if df_stations is not None and transit_matrices:
        print("--- 2. Тестирование расчета маршрута ---")
        
        # ОТЛАДКА: Поиск станции "Москва"
        print("Поиск станции 'Москва' в справочнике:")
        moscow_stations = search_station_names("Москва", df_stations, limit=5)
        if moscow_stations:
            print("Найдены варианты:")
            for s in moscow_stations:
                print(f"- {s}")
        else:
            print("Варианты для 'Москва' не найдены.")
        print("-" * 50)

        # ОТЛАДКА: Поиск станции "Новосибирск"
        print("Поиск станции 'Новосибирск' в справочнике:")
        novosibirsk_stations = search_station_names("Новосибирск", df_stations, limit=5)
        if novosibirsk_stations:
            print("Найдены варианты:")
            for s in novosibirsk_stations:
                print(f"- {s}")
        else:
            print("Варианты для 'Новосибирск' не найдены.")
        print("-" * 50)


        # Тестовый маршрут 1: от Москвы до Новосибирска
        # !!! ПРОВЕРЬТЕ И ИЗМЕНИТЕ ЭТИ НАЗВАНИЯ НА НАЙДЕННЫЕ ТОЧНЫЕ НАЗВАНИЯ ИЗ ВЫВОДА ВЫШЕ !!!
        station_1_a = "Москва-Пассажирская" # <-- Вставьте сюда точное название "Москвы"
        station_1_b = "Новосибирск-Главный" # <-- Вставьте сюда точное название "Новосибирска"
        
        # Дополнительная проверка, чтобы убедиться, что найденные станции существуют
        info_1_a = find_station_info(station_1_a, df_stations)
        info_1_b = find_station_info(station_1_b, df_stations)

        if not info_1_a:
            print(f"!!! Предупреждение: Станция '{station_1_a}' не найдена в справочнике для теста 1. Проверьте название.")
        if not info_1_b:
            print(f"!!! Предупреждение: Станция '{station_1_b}' не найдена в справочнике для теста 1. Проверьте название.")


        print(f"Рассчитываем расстояние от '{station_1_a}' до '{station_1_b}'...")
        
        result_1 = calculate_distance(station_1_a, station_1_b, df_stations, transit_matrices)
        
        if result_1['status'] == 'success':
            route = result_1['route']
            print("\n✅ Маршрут успешно рассчитан!")
            if route.get('is_same_station'):
                print(f"   Станция отправления и назначения совпадают. Расстояние: {route['total_distance']} км")
            else:
                print(f"   Станция отправления: {route['from']}")
                print(f"   Станция назначения: {route['to']}")
                print("-" * 30)
                print(f"   1. {route['from']} → {route['tpa_name']}: {route['distance_a_to_tpa']} км")
                print(f"   2. {route['tpa_name']} → {route['tpb_name']}: {route['distance_tpa_to_tpb']} км")
                print(f"   3. {route['tpb_name']} → {route['to']}: {route['distance_tpb_to_b']} км")
                print("-" * 30)
                print(f"   ИТОГОВОЕ ТАРИФНОЕ РАССТОЯНИЕ: {route['total_distance']} км")
        else:
            print(f"\n❌ Ошибка расчета: {result_1['message']}")

        print("\n" + "=" * 50 + "\n")

        # Тестовый маршрут 2: Станции с ошибкой (пример)
        station_2_a = "Неизвестная Станция"
        station_2_b = "Новосибирск-Главный" # Здесь можно оставить "Новосибирск-Главный" для демонстрации ошибки

        print(f"Рассчитываем расстояние от '{station_2_a}' до '{station_2_b}'...")
        result_2 = calculate_distance(station_2_a, station_2_b, df_stations, transit_matrices)
        if result_2['status'] == 'success':
            print(f"\n✅ Маршрут успешно рассчитан для '{station_2_a}' до '{station_2_b}': {result_2['route']['total_distance']} км")
        else:
            print(f"\n❌ Ошибка расчета: {result_2['message']}")

        print("\n" + "=" * 50 + "\n")
        
        # Тестовый маршрут 3: Одинаковые станции
        station_3_a = "Ясногорск"
        station_3_b = "Ясногорск"

        # Дополнительная проверка, чтобы убедиться, что найденные станции существуют
        info_3_a = find_station_info(station_3_a, df_stations)
        if not info_3_a:
            print(f"!!! Предупреждение: Станция '{station_3_a}' не найдена в справочнике для теста 3. Проверьте название.")


        print(f"Рассчитываем расстояние от '{station_3_a}' до '{station_3_b}'...")
        result_3 = calculate_distance(station_3_a, station_3_b, df_stations, transit_matrices)
        if result_3['status'] == 'success':
            route = result_3['route']
            print("\n✅ Маршрут успешно рассчитан!")
            if route.get('is_same_station'):
                print(f"   Станция отправления и назначения совпадают. Расстояние: {route['total_distance']} км")
        else:
            print(f"\n❌ Ошибка расчета: {result_3['message']}")
    else:
        print("\nПропуск тестирования расчета, так как данные не были загружены успешно.")