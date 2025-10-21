# services/notification_service.py
from datetime import time, datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import Bot

from db import SessionLocal
from models import Subscription, Tracking
from logger import get_logger

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time) -> tuple[int, int]:
        """
        Отправляет уведомления пользователям, чьи подписки соответствуют target_time.
        Возвращает (отправлено_уведомлений, всего_активных_подписок).
        """
        sent_count = 0
        total_active_subscriptions = 0

        # ✅ ЛОГИРОВАНИЕ: Начало запроса подписок
        logger.info(f"[Notification] Запрос активных подписок на время {target_time.strftime('%H:%M')}...")
        
        async with SessionLocal() as session:
            # Находим все активные подписки на целевое время
            result = await session.execute(
                select(Subscription)
                .filter(Subscription.is_active == True)
                .filter(Subscription.notification_time == target_time)
                .options(selectinload(Subscription.user)) # Загружаем пользователя
            )
            subscriptions = result.scalars().all()
            total_active_subscriptions = len(subscriptions)
            
            # ✅ ЛОГИРОВАНИЕ: Найденные подписки
            logger.info(f"[Notification] Найдено {total_active_subscriptions} активных подписок для рассылки.")


            for sub in subscriptions:
                if not sub.user or not sub.containers:
                    logger.warning(f"[Notification] Подписка ID {sub.id} пропущена (нет пользователя или контейнеров).")
                    continue
                
                # ✅ ЛОГИРОВАНИЕ: Обработка подписки
                logger.info(f"[Notification] Обработка подписки ID {sub.id} для user {sub.user.telegram_id} ({sub.subscription_name}).")

                # 1. Сбор данных для уведомления (только последний статус)
                container_data_list = []
                for ctn in sub.containers:
                    tracking_result = await session.execute(
                        select(Tracking)
                        .filter(Tracking.container_number == ctn)
                        .order_by(Tracking.operation_date.desc())
                        .limit(1)
                    )
                    tracking_info = tracking_result.scalar_one_or_none()
                    if tracking_info:
                        container_data_list.append(tracking_info)
                
                # 2. Форматирование сообщения (пример)
                if container_data_list:
                    message_parts = [f"🔔 **Отчет по подписке: {sub.subscription_name}** 🔔"]
                    for info in container_data_list:
                        message_parts.append(f"*{info.container_number}*: {info.operation} на {info.current_station} ({info.operation_date.strftime('%d.%m %H:%M')})")
                    
                    try:
                        # 3. Отправка
                        await self.bot.send_message(
                            chat_id=sub.user.telegram_id,
                            text="\n".join(message_parts),
                            parse_mode="Markdown"
                        )
                        sent_count += 1
                        # ✅ ЛОГИРОВАНИЕ: Успешная отправка
                        logger.info(f"🟢 [Notification] Успешно отправлено {len(container_data_list)} статусов пользователю {sub.user.telegram_id}.")
                        
                    except Exception as e:
                        logger.error(f"❌ [Notification] Ошибка отправки пользователю {sub.user.telegram_id}: {e}", exc_info=True)
                else:
                    logger.info(f"[Notification] Нет актуальных данных для контейнеров подписки ID {sub.id}.")

        # ✅ ЛОГИРОВАНИЕ: Завершение
        logger.info(f"✅ [Notification] Рассылка завершена. Итого: Отправлено сообщений: {sent_count}, Обработано подписок: {total_active_subscriptions}.")
        
        return sent_count, total_active_subscriptions