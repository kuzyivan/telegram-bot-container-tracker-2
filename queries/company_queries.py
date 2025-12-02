# queries/company_queries.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from logger import get_logger

logger = get_logger(__name__)

async def sync_terminal_to_company_containers(session: AsyncSession) -> int:
    """
    Массово копирует УНИКАЛЬНЫЕ контейнеры из terminal_containers в company_containers,
    если совпадает client == import_mapping_key.
    """
    
    # 1. Сначала очищаем форматирование (на всякий случай)
    # Это тяжелая операция, но для надежности стоит того.
    # Если база огромная, лучше делать это индексами, но пока так:
    
    sql = text("""
        INSERT INTO company_containers (company_id, container_number, created_at)
        SELECT DISTINCT 
            c.id, 
            tc.container_number, 
            NOW()
        FROM terminal_containers tc
        JOIN companies c ON TRIM(tc.client) = TRIM(c.import_mapping_key)
        WHERE NOT EXISTS (
            SELECT 1 FROM company_containers cc 
            WHERE cc.company_id = c.id 
              AND cc.container_number = tc.container_number
        );
    """)
    
    try:
        # Пытаемся выполнить вставку
        result = await session.execute(sql)
        await session.commit()
        
        # Получаем количество вставленных строк
        count = result.rowcount
        
        logger.info(f"✅ [Sync] Синхронизация завершена. Добавлено новых контейнеров в архив: {count}")
        return count
        
    except Exception as e:
        await session.rollback()
        logger.error(f"❌ [Sync] Ошибка синхронизации компаний: {e}", exc_info=True)
        return 0