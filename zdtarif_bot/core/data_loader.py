# core/data_loader.py

import pandas as pd
import glob
import os
import re

def load_kniga_2_rp(data_dir: str):
    """
    Загружает ТОЛЬКО файл 2-РП.csv.
    """
    try:
        file_path_list = glob.glob(os.path.join(data_dir, '*2-РП.csv'))
        if not file_path_list:
            raise FileNotFoundError
        file_path = file_path_list[0]
        
        df = pd.read_csv(
            file_path,
            skiprows=5,
            names=[
                'num', 'station_name', 'operations', 'railway', 
                'transit_points_raw', 'station_code'
            ],
            encoding='cp1251'
        )
        df['station_name'] = df['station_name'].str.strip()
        print(f"✅ Справочник станций (2-РП.csv) успешно загружен. Всего станций: {len(df)}")
        return df
    except FileNotFoundError:
        print(f"❌ Ошибка: Не найден файл '*2-РП.csv' в папке '{data_dir}'.")
        return None
    except Exception as e:
        print(f"❌ Произошла ошибка при загрузке 2-РП.csv: {e}")
        return None

def load_kniga_3_matrices(data_dir: str):
    """
    Загружает ТОЛЬКО файлы матриц 3-1 Рос.csv и 3-2 Рос.csv.
    """
    matrix_files = glob.glob(os.path.join(data_dir, '*3-1 Рос.csv')) + glob.glob(os.path.join(data_dir, '*3-2 Рос.csv'))
    
    if not matrix_files:
        print(f"❌ Ошибка: Не найдены файлы матриц '*3-1 Рос.csv' или '*3-2 Рос.csv' в папке '{data_dir}'.")
        return {}

    matrices = {}
    for file in matrix_files:
        try:
            base_name = os.path.basename(file)
            match = re.search(r'3-(.*?)\.csv', base_name, re.IGNORECASE)
            region_name = match.group(1).strip() if match else os.path.splitext(base_name)[0]

            df = pd.read_csv(file, skiprows=5, encoding='cp1251')
            
            df.iloc[:, 1] = df.iloc[:, 1].astype(str).str.strip()
            df = df.set_index(df.columns[1])
            df = df.drop(columns=[df.columns[0]])
            df.columns = df.columns.str.strip()

            matrices[region_name] = df
            print(f"✅ Матрица '{region_name}' успешно загружена.")
        except Exception as e:
            print(f"⚠️ Ошибка при обработке файла матрицы {file}: {e}")
            
    print(f"✅ Матрицы Книги 3 успешно загружены. Всего матриц: {len(matrices)}")
    return matrices