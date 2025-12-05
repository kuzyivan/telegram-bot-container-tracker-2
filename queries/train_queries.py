# queries/train_queries.py
"""
Запросы SQLAlchemy для получения информации о поездах и связанных контейнерах.
"""
# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
from sqlalchemy import select, func, desc, distinct, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from datetime import datetime

from db import SessionLocal
# ✅ Импортируем все нужные модели
from models import Tracking, Train
from model.terminal_container import TerminalContainer
from logger import get_logger
# --- КОНЕЦ ОБНОВЛЕННЫХ ИМПОРТОВ ---

logger = get_logger(__name__)

# =====================================================================
# (Функции get_all_train_codes, get_train_client_summary_by_code, get_first_container_in_train
#  остаются БЕЗ ИЗМЕНЕНИЙ)
# =====================================================================

async def get_all_train_codes() -> List[str]:
    """
    Получает список всех уникальных, непустых номеров поездов 
    из таблицы TerminalContainer.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(distinct(TerminalContainer.train))
            .where(TerminalContainer.train.isnot(None), TerminalContainer.train != '')
            .order_by(TerminalContainer.train)
        )
        train_codes = result.scalars().all()
        final_list: List[str] = list(train_codes) 
        
        logger.info(f"Найдено {len(final_list)} уникальных номеров поездов.")
        return final_list

async def get_train_client_summary_by_code(train_code: str) -> dict[str, int]:
    """
    Получает сводку по клиентам для указанного поезда (из TerminalContainer).
    Возвращает словарь {клиент: количество_контейнеров}.
    """
    summary = {}
    async with SessionLocal() as session:
        result = await session.execute(
            select(TerminalContainer.client, func.count(TerminalContainer.id).label('count'))
            .where(TerminalContainer.train == train_code)
            .group_by(TerminalContainer.client)
            .order_by(func.count(TerminalContainer.id).desc())
        )
        rows = result.mappings().all()
        summary = {row['client'] if row['client'] else 'Не указан': row['count'] for row in rows}
        
    if summary:
         logger.info(f"Найдена сводка для поезда {train_code}: {len(summary)} клиентов.")
    else:
         logger.warning(f"Сводка для поезда {train_code} не найдена в terminal_containers.")
         
    return summary


async def get_first_container_in_train(train_code: str) -> str | None:
     """
     Находит номер первого попавшегося контейнера в указанном поезде
     из таблицы terminal_containers.
     """
     async with SessionLocal() as session:
         result = await session.execute(
             select(TerminalContainer.container_number)
             .where(TerminalContainer.train == train_code)
             .limit(1)
         )
         container = result.scalar_one_or_none()
         if container:
             logger.debug(f"Найден пример контейнера {container} для поезда {train_code}")
         else:
              logger.debug(f"Не найден пример контейнера для поезда {train_code} в terminal_containers")
         return container

# =====================================================================
# === ✅ ОБНОВЛЕННЫЕ ФУНКЦИИ ДЛЯ ТАБЛИЦЫ TRAIN ===
# =====================================================================

async def upsert_train_on_upload(
    terminal_train_number: str, 
    container_count: int, 
    admin_id: int,
    overload_station_name: str | None = None,
    overload_date: datetime | None = None # <-- При загрузке он будет None
) -> Train | None:
    """
    Создает или обновляет запись в таблице 'trains' при загрузке файла поезда (Шаг 1 диалога).
    """
    async with SessionLocal() as session:
        try:
            stmt = pg_insert(Train).values(
                terminal_train_number=terminal_train_number,
                container_count=container_count,
                overload_station_name=overload_station_name,
                overload_date=overload_date # <-- Записываем None
            ).on_conflict_do_update(
                index_elements=['terminal_train_number'], 
                set_={
                    'container_count': container_count,
                    'overload_station_name': overload_station_name,
                    'overload_date': overload_date, # <--- Обновляем на None
                    'updated_at': func.now()
                }
            ).returning(Train) 

            result = await session.execute(stmt)
            await session.commit()
            
            created_or_updated_train = result.scalar_one()
            logger.info(f"[TrainTable] Админ {admin_id} создал/обновил поезд {terminal_train_number} (Перегруз: {overload_station_name or 'Нет'})")
            return created_or_updated_train
            
        except Exception as e:
            await session.rollback()
            logger.error(f"[TrainTable] Ошибка при upsert поезда {terminal_train_number}: {e}", exc_info=True)
            return None

async def update_train_status_from_tracking_data(
    terminal_train_number: str, 
    tracking_data: Tracking,
    session: AsyncSession
) -> bool:
    """
    Обновляет запись Train данными из последней дислокации (Tracking).
    ВЫПОЛНЯЕТ ЛОГИКУ ПРОВЕРКИ СТАНЦИИ ПЕРЕГРУЗА И ЗАЩИТУ ОТ 'ЧУЖИХ' РЕЙСОВ.
    """
    if not tracking_data:
        return False
        
    try:
        # --- Шаг 1: Получаем текущие данные поезда ---
        train = await get_train_details(terminal_train_number, session)
        if not train:
            logger.warning(f"[TrainTable] Поезд {terminal_train_number} не найден в Train, создаю новую запись...")
            train = Train(terminal_train_number=terminal_train_number)
            session.add(train)
            await session.flush()

        # 🔥 ЗАЩИТА 1: ПРОВЕРКА НАПРАВЛЕНИЯ (NEW) 🔥
        # Если у поезда уже задана станция назначения, а в новой дислокации она ДРУГАЯ,
        # значит этот контейнер уехал в новый рейс. Игнорируем обновление поезда.
        if train.destination_station and tracking_data.to_station:
            train_dest = train.destination_station.strip().lower()
            track_dest = tracking_data.to_station.strip().lower()
            
            # Сравниваем назначения. Если не совпадают — это "левый" рейс.
            # (Добавляем проверку длины, чтобы избежать ошибок на пустых строках)
            if len(train_dest) > 2 and len(track_dest) > 2 and train_dest != track_dest:
                logger.warning(f"[TrainTable] 🛡 ИГНОР ОБНОВЛЕНИЯ для поезда {terminal_train_number}: "
                               f"Назначение поезда '{train.destination_station}' != Назначение контейнера '{tracking_data.to_station}'. "
                               f"Похоже на следующий рейс.")
                return False

        # --- Шаг 2 (Существующая логика): ПРОВЕРКА "ДОСТАВЛЕН" ---
        if (train.last_known_station and 
            train.destination_station and 
            train.last_operation):
            
            dest_station_norm = train.destination_station.lower().strip()
            last_station_norm = train.last_known_station.lower().strip()
            
            # Ищем "выгрузка"
            is_unloaded = "выгрузка" in train.last_operation.lower()

            # Если поезд уже на станции назначения и выгружен
            if (dest_station_norm in last_station_norm) and is_unloaded:
                # Мы не обновляем статус, если поезд уже завершен
                logger.info(f"[TrainTable] Поезд {terminal_train_number} уже финализирован (Выгрузка на назначении). Обновление пропущено.")
                return False

        # --- Шаг 3: Собираем данные для обновления (без изменений) ---
        update_data = {
            "rzd_train_number": tracking_data.train_number,
            "last_known_station": tracking_data.current_station,
            "last_known_road": tracking_data.operation_road,
            "last_operation": tracking_data.operation,
            "last_operation_date": tracking_data.operation_date,
            "km_remaining": tracking_data.km_left,
            "eta_days": tracking_data.forecast_days,
            "destination_station": tracking_data.to_station, # Обновит назначение, только если оно было пустым (см. Защиту 1)
        }
        
        if tracking_data.trip_start_datetime:
            start_dt = tracking_data.trip_start_datetime
            update_data["departure_date"] = start_dt.date() if isinstance(start_dt, datetime) else start_dt

        # --- Логика перегруза (без изменений) ---
        if (train.overload_station_name and 
            not train.overload_date and 
            tracking_data.current_station):
            
            admin_station = train.overload_station_name.lower().strip()
            current_station = tracking_data.current_station.lower()
            
            if admin_station in current_station:
                update_data["overload_date"] = tracking_data.operation_date

        # --- Шаг 4: Обновляем БД ---
        for key, value in update_data.items():
            setattr(train, key, value)
        setattr(train, 'updated_at', func.now())
        
        return True
            
    except Exception as e:
        logger.error(f"[TrainTable] Ошибка при обновлении статуса поезда {terminal_train_number}: {e}", exc_info=True)
        return False

async def get_train_details(
    terminal_train_number: str, 
    session: AsyncSession | None = None
) -> Train | None:
    """
    Получает полную запись о поезде из таблицы Train по его ТЕРМИНАЛЬНОМУ номеру.
    Может работать как с внешней сессией, так и создавать свою.
    """
    if session:
        return await _get_train_details_internal(terminal_train_number, session)
    else:
        async with SessionLocal() as new_session:
            return await _get_train_details_internal(terminal_train_number, new_session)

async def _get_train_details_internal(
    terminal_train_number: str, 
    session: AsyncSession
) -> Train | None:
    """Внутренняя логика запроса."""
    result = await session.execute(
        select(Train).where(Train.terminal_train_number == terminal_train_number)
    )
    return result.scalar_one_or_none()

# --- ✅ "УМНАЯ" ФУНКЦИЯ ПОИСКА ДИСЛОКАЦИИ (без изменений) ---
async def get_latest_active_tracking_for_train(terminal_train_number: str) -> Tracking | None:
    """
    Находит самую последнюю запись дислокации для поезда,
    которая содержит АКТУАЛЬНЫЙ номер поезда РЖД (не '0' и не NULL).
    
    Если такой нет, ищет ЛЮБУЮ последнюю запись (fallback).
    """
    async with SessionLocal() as session:
        try:
            # 1. Находим все контейнеры, связанные с этим терминальным поездом
            container_rows = await session.execute(
                select(TerminalContainer.container_number)
                .where(TerminalContainer.train == terminal_train_number)
            )
            container_list = container_rows.scalars().all()

            if not container_list:
                logger.warning(f"[TrainTable] Не найдено контейнеров в TerminalContainer для поезда {terminal_train_number}")
                return None
            
            # 2. Ищем последнюю запись в Tracking для ЛЮБОГО из этих контейнеров,
            #    ГДЕ train_number (номер РЖД) не '0' и не NULL.
            latest_active_tracking = await session.execute(
                select(Tracking)
                .where(Tracking.container_number.in_(container_list))
                .where(Tracking.train_number.isnot(None))
                .where(Tracking.train_number != '0') # <-- Ключевое условие
                .order_by(Tracking.operation_date.desc())
                .limit(1)
            )
            
            tracking_object = latest_active_tracking.scalar_one_or_none()
            
            if tracking_object:
                logger.info(f"[TrainTable] Найдена активная дислокация для {terminal_train_number} (Поезд РЖД: {tracking_object.train_number})")
                return tracking_object
            else:
                logger.warning(f"[TrainTable] Не найдено АКТИВНОЙ дислокации (с номером поезда РЖД) для {terminal_train_number}.")
                # --- ✅ FALLBACK: Ищем ЛЮБУЮ последнюю ---
                logger.info(f"[TrainTable] Fallback: Ищу ЛЮБУЮ последнюю дислокацию для {terminal_train_number}...")
                latest_any_tracking = await session.execute(
                    select(Tracking)
                    .where(Tracking.container_number.in_(container_list))
                    .order_by(Tracking.operation_date.desc())
                    .limit(1)
                )
                tracking_object_any = latest_any_tracking.scalar_one_or_none()
                if tracking_object_any:
                    logger.info(f"[TrainTable] Fallback: Найдена дислокация (возможно, с РЖД поездом '0')")
                    return tracking_object_any
                else:
                    logger.error(f"[TrainTable] Fallback: ВООБЩЕ нет дислокации для поезда {terminal_train_number}.")
                    return None
                
        except Exception as e:
            logger.error(f"[TrainTable] Ошибка в get_latest_active_tracking_for_train: {e}", exc_info=True)
            return None