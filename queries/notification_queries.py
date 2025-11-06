# (Вставьте это в queries/notification_queries.py,
# заменив старую функцию get_tracking_data_for_containers)

# --- Убедитесь, что эти импорты ЕСТЬ вверху файла ---
import logging
from sqlalchemy.future import select
from sqlalchemy.orm import aliased
from sqlalchemy import func
from db import async_sessionmaker
from models import Tracking
# ---

logger = logging.getLogger(__name__)

async def get_tracking_data_for_containers(container_numbers: list[str]) -> list[Tracking]:
    """
    Получает ПОСЛЕДНЮЮ запись о дислокации для каждого 
    контейнера из списка.
    
    (Версия 2 - Исправлена ошибка 'function to_timestamp(timestamp... does not exist')
    """
    if not container_numbers:
        return []
        
    logger.info(f"[Queries] Поиск последних данных для {len(container_numbers)} контейнеров.")
    
    try:
        # Убедимся, что async_sessionmaker вызывается со скобками ()
        async with async_sessionmaker() as session:
            
            # --- ИСПРАВЛЕННЫЙ ЗАПРОС ---
            # Создаем подзапрос (Common Table Expression - CTE)
            subquery = select(
                Tracking,
                func.row_number().over(
                    partition_by=Tracking.container_number,
                    
                    # --- ИСПРАВЛЕНИЕ ---
                    # Раньше было: func.TO_TIMESTAMP(Tracking.operation_date, ...).desc()
                    # Это вызывало ошибку, так как operation_date - УЖЕ TIMESTAMP.
                    # Теперь мы сортируем напрямую по полю.
                    order_by=Tracking.operation_date.desc()
                    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                    
                ).label('rn')
            ).where(Tracking.container_number.in_(container_numbers)).subquery()

            # Создаем псевдоним (alias) для CTE
            t_aliased = aliased(Tracking, subquery)

            # Выбираем только те строки, где rn = 1 (т.е. самые последние)
            stmt = select(t_aliased).where(subquery.c.rn == 1)

            result = await session.execute(stmt) 
            return result.scalars().all()

    except Exception as e:
        logger.error(f"Ошибка в get_tracking_data_for_containers: {e}", exc_info=True)
        return []

# (Оставьте остальные функции в файле, если они там есть)