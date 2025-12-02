# queries/company_queries.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from logger import get_logger

logger = get_logger(__name__)

async def sync_terminal_to_company_containers(session: AsyncSession) -> int:
    """
    Массово копирует контейнеры из terminal_containers в company_containers,
    если совпадает client == import_mapping_key.
    Игнорирует дубликаты.
    """
    # Этот SQL запрос делает следующее:
    # 1. Берет ID компании и Номер контейнера.
    # 2. Соединяет (JOIN) таблицу терминала и компаний по названию клиента.
    # 3. Вставляет только те записи, которых еще нет в company_containers (ON CONFLICT DO NOTHING).
    
    sql = text("""
        INSERT INTO company_containers (company_id, container_number, created_at)
        SELECT 
            c.id, 
            tc.container_number, 
            NOW()
        FROM terminal_containers tc
        JOIN companies c ON tc.client = c.import_mapping_key
        ON CONFLICT (id) DO NOTHING -- (или DO NOTHING, если нет уникального индекса пары)
        -- Чтобы избежать дублей логически, добавим WHERE NOT EXISTS:
        WHERE NOT EXISTS (
            SELECT 1 FROM company_containers cc 
            WHERE cc.company_id = c.id AND cc.container_number = tc.container_number
        );
    """)
    
    try:
        result = await session.execute(sql)
        await session.commit()
        # rowcount в INSERT..SELECT может быть неточным в некоторых драйверах, но попробуем
        count = result.rowcount
        logger.info(f"✅ [Sync] Синхронизация завершена. Добавлено связей: {count}")
        return count
    except Exception as e:
        await session.rollback()
        logger.error(f"❌ [Sync] Ошибка синхронизации компаний: {e}", exc_info=True)
        return 0