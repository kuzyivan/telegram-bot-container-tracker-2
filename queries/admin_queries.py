# queries/admin_queries.py
from typing import Sequence, List, Dict
from sqlalchemy import text, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import selectinload

from config import ADMIN_CHAT_ID
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from logger import get_logger

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
    Возвращает все активные подписки на отслеживание, объединяя данные с пользователями.
    """
    async with SessionLocal() as session:
        query = text("""
            SELECT
                ts.id, ts.display_id, ts.subscription_name,
                u.telegram_id, u.username,
                ts.containers, ts.notify_time, ts.is_active
            FROM tracking_subscriptions ts
            LEFT JOIN users u ON ts.user_telegram_id = u.telegram_id
            ORDER BY u.telegram_id, ts.id
        """)
        result = await session.execute(query)
        subs = result.fetchall()
        if not subs:
            return None, None

        columns = list(result.keys())
        return subs, columns

async def get_data_for_test_notification() -> Dict[str, List[List[str]]]:
    """
    Собирает данные по всем подписчикам для тестовой рассылки.
    Возвращает словарь { 'имя_пользователя': [[строка_данных], ...], ... }
    """
    logger.info("[test_notify_data] Начинаю сбор данных для тестовой рассылки.")
    data_per_user: Dict[str, List[List[str]]] = {}
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrackingSubscription).options(selectinload(TrackingSubscription.user))
        )
        subscriptions = result.scalars().all()
        logger.info(f"[test_notify_data] Найдено {len(subscriptions)} активных подписок.")

        for sub in subscriptions:
            if not sub.user:
                logger.warning(f"[test_notify_data] У подписки ID {sub.id} нет связанного пользователя, пропущена.")
                continue

            user_label = f"{sub.user.username or sub.user_telegram_id} (id:{sub.user_telegram_id})"
            logger.info(f"[test_notify_data] Обрабатываю подписку '{sub.subscription_name}' для пользователя: {user_label}")
            
            rows = []
            # <<< ИСПРАВЛЕНИЕ: Делаем проверку на пустой список явной для Pylance
            if not sub.containers or len(sub.containers) == 0:
                logger.warning(f"[test_notify_data] У подписки '{sub.subscription_name}' пустой список контейнеров.")
            else:
                for container in sub.containers:
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
                        rows.append(list(track_row))
            
            sheet_name = f"{user_label} - {sub.subscription_name}"
            if not rows:
                rows.append(["Нет данных по контейнерам"] + [""] * 10)
            
            data_per_user[sheet_name] = rows
            
    logger.info("[test_notify_data] Сбор данных завершен.")
    return data_per_user

async def get_admin_user_for_email(admin_id: int) -> User | None:
    """
    Находит администратора по ID.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == admin_id)
        )
        return result.scalar_one_or_none()