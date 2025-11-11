# queries/train_queries.py
"""
Запросы SQLAlchemy для получения информации о поездах и связанных контейнерах.
"""
from sqlalchemy import select, func, desc, distinct, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from datetime import datetime

from db import SessionLocal
from models import Tracking, Train
from model.terminal_container import TerminalContainer
from logger import get_logger

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
    session: AsyncSession # <--- ✅ Принимаем сессию
) -> bool:
    """
    Обновляет запись Train данными из последней дислокации (Tracking).
    ВЫПОЛНЯЕТ ЛОГИКУ ПРОВЕРКИ СТАНЦИИ ПЕРЕГРУЗА.
    """
    if not tracking_data:
        return False
        
    try:
        # --- ✅ Шаг 1: Получаем текущие данные поезда (в той же сессии) ---
        train = await get_train_details(terminal_train_number, session)
        if not train:
            logger.warning(f"[TrainTable] Хотел обновить {terminal_train_number}, но не нашел запись в Train.")
            return False

        # --- ✅ Шаг 2: Собираем основные данные для обновления ---
        update_data = {
            "rzd_train_number": tracking_data.train_number,
            "last_known_station": tracking_data.current_station,
            "last_known_road": tracking_data.operation_road,
            "last_operation": tracking_data.operation,
            "last_operation_date": tracking_data.operation_date,
            "km_remaining": tracking_data.km_left,
            "eta_days": tracking_data.forecast_days,
            "destination_station": tracking_data.to_station,
        }
        
        if tracking_data.trip_start_datetime:
            start_dt = tracking_data.trip_start_datetime
            update_data["departure_date"] = start_dt.date() if isinstance(start_dt, datetime) else start_dt

        # --- ✅ Шаг 3: ЛОГИКА ПЕРЕГРУЗА ---
        # Проверяем, если:
        # 1. Станция перегруза админом ЗАДАНА
        # 2. Дата перегруза в БД ЕЩЕ НЕ УСТАНОВЛЕНА (None)
        # 3. Станция дислокации (current_station) СУЩЕСТВУЕТ
        if (train.overload_station_name and 
            not train.overload_date and 
            tracking_data.current_station):
            
            # Сравниваем "Чемской" (из БД) с "ЧЕМСКОЙ (850308)" (из дислокации)
            # Используем lower() для нечувствительности к регистру
            admin_station = train.overload_station_name.lower()
            current_station = tracking_data.current_station.lower()
            
            if admin_station in current_station:
                # СОВПАДЕНИЕ! Устанавливаем дату
                logger.info(f"✅ [Перегруз] Станция совпала! Поезд {terminal_train_number} достиг {train.overload_station_name}.")
                update_data["overload_date"] = tracking_data.operation_date
            else:
                logger.info(f"[Перегруз] Поезд {terminal_train_number} еще не на станции '{admin_station}' (сейчас на '{current_station}')")

        # --- ✅ Шаг 4: Обновляем БД ---
        stmt = update(Train).where(
            Train.terminal_train_number == terminal_train_number
        ).values(
            **update_data,
            updated_at=func.now()
        )
        
        result = await session.execute(stmt)
        # (Коммит будет во внешней функции dislocation_importer)
        
        if result.rowcount > 0:
            logger.info(f"[TrainTable] Обновлен статус поезда {terminal_train_number} (РЖД: {tracking_data.train_number})")
            return True
        else:
            return False
            
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
    
    # --- ✅ ЛОГИКА УПРАВЛЕНИЯ СЕССИЕЙ ---
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