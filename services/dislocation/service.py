import os
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from services.dislocation.excel_reader import read_excel_data
from services.dislocation.db_updater import import_tracking_data_to_db, update_train_statuses_from_tracking
from logger import get_logger

logger = get_logger(__name__)

async def process_dislocation_file(session: AsyncSession, filepath: str) -> Dict[str, Any]:
    """
    Оркестратор обработки файла дислокации.
    
    Выполняет полный цикл:
    1. Чтение Excel файла.
    2. Обновление таблицы Tracking (и добавление истории).
    3. Обновление статусов поездов (Train) на основе новых данных.
    """
    stats = {
        "file": os.path.basename(filepath),
        "total_rows": 0,
        "inserted": 0,
        "updated": 0,
        "trains_updated": 0,
        "status": "success",
        "error": None
    }

    logger.info(f"[DislocationService] Начинаем обработку файла: {filepath}")

    if not os.path.exists(filepath):
        msg = f"Файл не найден: {filepath}"
        logger.error(msg)
        stats["status"] = "error"
        stats["error"] = msg
        return stats

    try:
        # 1. Чтение данных из Excel
        data_rows = read_excel_data(filepath)
        
        if data_rows is None:
            msg = "Не удалось прочитать Excel файл или формат неверен."
            stats["status"] = "error"
            stats["error"] = msg
            return stats
            
        stats["total_rows"] = len(data_rows)
        
        if not data_rows:
            logger.warning("[DislocationService] Файл пуст или не содержит валидных строк.")
            return stats

        # 2. Импорт данных в БД (Tracking + History)
        inserted, updated, processed_objects = await import_tracking_data_to_db(session, data_rows)
        stats["inserted"] = inserted
        stats["updated"] = updated
        
        # 3. Обновление статусов поездов
        if processed_objects:
            trains_count = await update_train_statuses_from_tracking(session, processed_objects)
            stats["trains_updated"] = trains_count
            
        # Фиксируем изменения
        await session.commit()
        
        logger.info(f"[DislocationService] Обработка завершена. Статистика: {stats}")

    except Exception as e:
        logger.error(f"[DislocationService] Ошибка при обработке файла: {e}", exc_info=True)
        await session.rollback()
        stats["status"] = "error"
        stats["error"] = str(e)
    
    return stats