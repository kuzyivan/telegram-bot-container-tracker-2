# queries/train_queries.py
"""
Запросы SQLAlchemy для получения информации о поездах и связанных контейнерах.
"""
# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
from sqlalchemy import select, func, desc, distinct, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
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
# СПИСОК ПОЕЗДОВ (без изменений)
# =====================================================================

async def get_all_train_codes() -> List[str]:
    """
    Получает список всех уникальных, непустых номеров поездов 
    из таблицы TerminalContainer.
    """
    async with SessionLocal() as session:
        # Фильтруем пустые значения (None и пустая строка) прямо в запросе
        result = await session.execute(
            select(distinct(TerminalContainer.train))
            .where(TerminalContainer.train.isnot(None), TerminalContainer.train != '')
            .order_by(TerminalContainer.train)
        )
        train_codes = result.scalars().all()
        final_list: List[str] = list(train_codes) 
        
        logger.info(f"Найдено {len(final_list)} уникальных номеров поездов.")
        return final_list

# =====================================================================
# СВОДКА ПО КЛИЕНТАМ (без изменений)
# =====================================================================

async def get_train_client_summary_by_code(train_code: str) -> dict[str, int]:
    """
    Получает сводку по клиентам для указанного поезда (из TerminalContainer).
    Возвращает словарь {клиент: количество_контейнеров}.
    """
    summary = {}
    async with SessionLocal() as session:
        # Выбираем контейнеры на терминале с нужным номером поезда
        # и группируем по клиенту, считая количество контейнеров
        result = await session.execute(
            select(TerminalContainer.client, func.count(TerminalContainer.id).label('count'))
            .where(TerminalContainer.train == train_code)
            .group_by(TerminalContainer.client)
            .order_by(func.count(TerminalContainer.id).desc()) # Сортируем по убыванию количества
        )
        rows = result.mappings().all() # Получаем результат как список словарей
        
        # Преобразуем результат в нужный формат
        summary = {row['client'] if row['client'] else 'Не указан': row['count'] for row in rows}
        
    if summary:
         logger.info(f"Найдена сводка для поезда {train_code}: {len(summary)} клиентов.")
    else:
         logger.warning(f"Сводка для поезда {train_code} не найдена в terminal_containers.")
         
    return summary


# =====================================================================
# КОНТРОЛЬНЫЙ КОНТЕЙНЕР (без изменений)
# =====================================================================

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
# === ✅ НОВЫЕ И ОБНОВЛЕННЫЕ ФУНКЦИИ ДЛЯ ТАБЛИЦЫ TRAIN ===
# =====================================================================

async def upsert_train_on_upload(
    terminal_train_number: str, # <--- ✅ ИЗМЕНЕНО
    container_count: int, 
    admin_id: int,
    overload_station_name: str | None = None,
    overload_date: datetime | None = None
) -> Train | None:
    """
    Создает или обновляет запись в таблице 'trains' при загрузке файла поезда (Шаг 1 диалога).
    """
    async with SessionLocal() as session:
        try:
            # 1. Создаем оператор INSERT ... ON CONFLICT DO UPDATE
            stmt = pg_insert(Train).values(
                terminal_train_number=terminal_train_number, # <--- ✅ ИЗМЕНЕНО
                container_count=container_count,
                overload_station_name=overload_station_name,
                overload_date=overload_date
            ).on_conflict_do_update(
                index_elements=['terminal_train_number'], # <--- ✅ ИЗМЕНЕНО (Уникальный ключ)
                set_={
                    'container_count': container_count,
                    'overload_station_name': overload_station_name,
                    'overload_date': overload_date,
                    'updated_at': func.now()
                }
            ).returning(Train) # Возвращаем обновленную или созданную строку

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
    tracking_data: Tracking
) -> bool:
    """
    Обновляет запись Train данными из последней дислокации (Tracking).
    Вызывается админом при загрузке ИЛИ планировщиком.
    """
    if not tracking_data:
        return False
        
    async with SessionLocal() as session:
        try:
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
            
            # Обновляем дату отправления (только если она есть)
            if tracking_data.trip_start_datetime:
                start_dt = tracking_data.trip_start_datetime
                update_data["departure_date"] = start_dt.date() if isinstance(start_dt, datetime) else start_dt

            stmt = update(Train).where(
                Train.terminal_train_number == terminal_train_number
            ).values(
                **update_data,
                updated_at=func.now()
            )
            
            result = await session.execute(stmt)
            await session.commit()
            
            if result.rowcount > 0:
                logger.info(f"[TrainTable] Обновлен статус поезда {terminal_train_number} (РЖД: {tracking_data.train_number})")
                return True
            else:
                logger.warning(f"[TrainTable] Хотел обновить {terminal_train_number}, но не нашел запись в Train.")
                return False
                
        except Exception as e:
            await session.rollback()
            logger.error(f"[TrainTable] Ошибка при обновлении статуса поезда {terminal_train_number}: {e}", exc_info=True)
            return False

async def get_train_details(terminal_train_number: str) -> Train | None:
    """
    Получает полную запись о поезде из таблицы Train по его ТЕРМИНАЛЬНОМУ номеру.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(Train).where(Train.terminal_train_number == terminal_train_number)
        )
        return result.scalar_one_or_none()