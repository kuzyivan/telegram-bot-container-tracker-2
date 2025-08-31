# queries/admin_queries.py
from typing import Sequence, List, Dict
from sqlalchemy import text, select
from sqlalchemy.engine import Row

from config import ADMIN_CHAT_ID
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
# --- ДОБАВЛЕНО: Импорт логгера ---
from logger import get_logger

# --- ДОБАВЛЕНО: Инициализация логгера ---
logger = get_logger(__name__)


async def get_daily_stats() -> Sequence[Row]:
    """
    Возвращает статистику по запросам контейнеров за последние 24 часа,
    исключая администратора.
    """
    async with SessionLocal() as session:
        query = text("""
            SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS request_count,
                   STRING_AGG(DISTINCT container_number, ', ') AS containers
            FROM stats
            WHERE timestamp >= NOW() - INTERVAL '1 day'
              AND user_id != :admin_id
            GROUP BY user_id, username
            ORDER BY request_count DESC
        """)
        result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
        return result.fetchall()

async def get_all_stats_for_export() -> tuple[Sequence[Row] | None, list[str] | None]:
    """
    Возвращает все записи из таблицы 'stats' для экспорта в Excel.
    """
    async with SessionLocal() as session:
        query = text("SELECT * FROM stats WHERE user_id != :admin_id")
        result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
        rows = result.fetchall()
        if not rows:
            return None, None
        
        columns = list(result.keys())
        return rows, columns

async def get_all_tracking_subscriptions() -> tuple[Sequence[Row] | None, list[str] | None]:
    """
    Возвращает все активные подписки на отслеживание.
    """
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT * FROM tracking_subscriptions"))
        subs = result.fetchall()
        if not subs:
            return None, None

        columns = list(result.keys())
        return subs, columns


# --- ОБНОВЛЁННАЯ ФУНКЦИЯ С ЛОГИРОВАНИЕМ ---
async def get_data_for_test_notification() -> Dict[str, List[List[str]]]:
    """
    Собирает данные по всем подписчикам для тестовой рассылки.
    Возвращает словарь { 'имя_пользователя': [[строка_данных], ...], ... }
    """
    logger.info("[test_notify_data] Начинаю сбор данных для тестовой рассылки.")
    data_per_user: Dict[str, List[List[str]]] = {}
    async with SessionLocal() as session:
        result = await session.execute(select(TrackingSubscription))
        subscriptions = result.scalars().all()
        logger.info(f"[test_notify_data] Найдено {len(subscriptions)} активных подписок.")

        for sub in subscriptions:
            user_label = f"{sub.username or sub.user_id} (id:{sub.user_id})"
            logger.info(f"[test_notify_data] Обрабатываю пользователя: {user_label}")
            
            # Очень важный лог: смотрим, какие именно контейнеры записаны в подписке
            logger.info(f"[test_notify_data] Контейнеры для пользователя: {sub.containers} (тип: {type(sub.containers)})")
            
            rows = []
            if not sub.containers:  # type: ignore
                logger.warning(f"[test_notify_data] У пользователя {user_label} пустой список контейнеров в подписке.")
            else:
                for container in sub.containers:
                    # Логируем каждый контейнер перед запросом
                    logger.info(f"[test_notify_data] -> Ищу контейнер: '{container}' (тип: {type(container)})")

                    res = await session.execute(
                        select(
                            Tracking.container_number, Tracking.from_station, Tracking.to_station,
                            Tracking.current_station, Tracking.operation, Tracking.operation_date,
                            Tracking.waybill, Tracking.km_left, Tracking.forecast_days,
                            Tracking.wagon_number, Tracking.operation_road
                        ).filter(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
                    )
                    
                    track_row = res.first()
                    
                    if track_row:
                        logger.info(f"[test_notify_data] -> ✅ НАЙДЕН: '{container}'")
                        rows.append(list(track_row))
                    else:
                        logger.warning(f"[test_notify_data] -> ❌ НЕ НАЙДЕН: '{container}'")

            logger.info(f"[test_notify_data] Для пользователя {user_label} собрано {len(rows)} строк данных.")
            if not rows:
                rows.append(["Нет данных"] + [""] * 10)
            
            data_per_user[user_label] = rows
            
    logger.info("[test_notify_data] Сбор данных завершен.")
    return data_per_user


async def get_admin_user_for_email(admin_id: int) -> User | None:
    """
    Находит администратора по ID и проверяет, включены ли у него email-уведомления.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == admin_id, User.email_enabled == True)
        )
        return result.scalar_one_or_none()