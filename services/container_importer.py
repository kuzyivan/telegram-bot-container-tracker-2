# services/container_importer.py
"""
Сервис для импорта данных о погруженных и отправленных контейнерах
из файлов 'Погрузка' и 'Отправка' с почты.
"""
import os
import pandas as pd
from sqlalchemy import select, update
import logging # Используем стандартный logging, если logger не импортирован иначе

from db import SessionLocal
# ✅ Исправляем импорт TerminalContainer
from model.terminal_container import TerminalContainer 
from logger import get_logger

logger = get_logger(__name__)

# Константы для названий колонок (можно вынести в config.py)
COL_CONTAINER = "Номер контейнера"
COL_CLIENT = "Клиент"
COL_DATE = "Дата приема" # Предполагаем, что колонка одна для даты/времени или только дата
COL_TIME = "Время приема" # Если время в отдельной колонке
COL_TRAIN = "Номер поезда"
COL_STATUS_LOADED = "ПОГРУЖЕН" # Статус для файла "Погрузка"
COL_STATUS_DISPATCHED = "ОТПРАВЛЕН" # Статус для файла "Отправка"


async def import_loaded_and_dispatch_from_excel(filepath: str):
    """
    Обрабатывает Excel-файл (Погрузка или Отправка) и обновляет статусы
    и номера поездов для контейнеров в таблице terminal_containers.
    """
    filename = os.path.basename(filepath).lower()
    is_loading_report = "погрузка" in filename
    is_dispatch_report = "отправка" in filename

    if not is_loading_report and not is_dispatch_report:
        logger.warning(f"Файл '{filename}' не является отчетом о погрузке или отправке. Пропуск.")
        return 0 # Возвращаем 0 обработанных

    logger.info(f"Начинаю обработку файла '{filename}'...")

    try:
        # skiprows=1 предполагаем, что заголовок на второй строке
        df = pd.read_excel(filepath, skiprows=1) 
        df.columns = [str(c).strip() for c in df.columns] # Очищаем заголовки

        if COL_CONTAINER not in df.columns:
            logger.error(f"В файле '{filename}' отсутствует обязательная колонка '{COL_CONTAINER}'. Обработка прервана.")
            return 0

        update_count = 0
        async with SessionLocal() as session:
            async with session.begin():
                for index, row in df.iterrows():
                    container_number = str(row[COL_CONTAINER]).strip().upper()
                    if not container_number or len(container_number) != 11:
                        logger.warning(f"Пропущена строка {index+2}: некорректный номер контейнера '{container_number}'")
                        continue

                    data_to_update = {}

                    # Определяем статус в зависимости от типа файла
                    if is_loading_report:
                         data_to_update['status'] = COL_STATUS_LOADED
                    elif is_dispatch_report:
                         data_to_update['status'] = COL_STATUS_DISPATCHED

                         # В файле отправки может быть номер поезда
                         if COL_TRAIN in df.columns and pd.notna(row[COL_TRAIN]):
                             data_to_update['train'] = str(row[COL_TRAIN]).strip().upper()

                    if not data_to_update: # Если нечего обновлять
                        continue

                    # Выполняем обновление
                    stmt = (
                        update(TerminalContainer)
                        .where(TerminalContainer.container_number == container_number)
                        .values(**data_to_update)
                    )
                    result = await session.execute(stmt)

                    if result.rowcount > 0:
                        update_count += 1
                        logger.debug(f"Контейнер {container_number} обновлен: {data_to_update}")
                    else:
                        logger.warning(f"Контейнер {container_number} из файла '{filename}' не найден в базе terminal_containers.")

            # Коммит произойдет автоматически

        logger.info(f"✅ Обработка файла '{filename}' завершена. Обновлено контейнеров: {update_count}.")
        return update_count

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке файла '{filename}': {e}", exc_info=True)
        return 0 # Возвращаем 0 в случае ошибки