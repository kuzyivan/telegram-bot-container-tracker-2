# queries/train_queries.py
"""
Запросы SQLAlchemy для получения информации о поездах и связанных контейнерах.
"""
# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
from sqlalchemy import select, func, desc, distinct, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from typing import List
from datetime import datetime

from db import SessionLocal
# ✅ Исправляем импорт TerminalContainer и добавляем Train
from models import Tracking, Train
from model.terminal_container import TerminalContainer
from logger import get_logger
# --- КОНЕЦ ОБНОВЛЕННЫХ ИМПОРТОВ ---

logger = get_logger(__name__)

# =====================================================================
# НОВАЯ ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ СПИСКА ПОЕЗДОВ (Исправлен тип возврата)
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
# КОНЕЦ НОВОЙ ФУНКЦИИ
# =====================================================================


async def get_train_client_summary_by_code(train_code: str) -> dict[str, int]:
    """
    Получает сводку по клиентам для указанного поезда.
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
         logger.warning(f"Сводка для поезда {train_code} не найдена (нет контейнеров с таким поездом в terminal_containers).")
         
    return summary


async def get_first_container_in_train(train_code: str) -> str | None:
     """
     Находит номер первого попавшегося контейнера в указанном поезде
     из таблицы terminal_containers (для получения примера дислокации).
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

# --- ✅ ОБНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ ТАБЛИЦЫ TRAIN ---

async def upsert_train_on_upload(
    terminal_train_number: str, # <--- ✅ ИЗМЕНЕНО
    container_count: int, 
    admin_id: int,
    overload_station_name: str | None = None,
    overload_date: datetime | None = None
) -> Train | None:
    """
    Создает или обновляет запись в таблице 'trains' при загрузке файла поезда.
    (Upsert = Update + Insert)
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
                index_elements=['terminal_train_number'], # <--- ✅ ИЗМЕНЕНО
                set_={
                    'container_count': container_count,
                    'overload_station_name': overload_station_name,
                    'overload_date': overload_date,
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