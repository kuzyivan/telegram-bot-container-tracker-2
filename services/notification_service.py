# services/notification_service.py
from datetime import time, datetime
import asyncio
import os # Для удаления временного файла
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import Bot
from typing import List, Any # Для типизации Excel-данных

from db import SessionLocal
# Импортируем SubscriptionEmail для корректной загрузки связей
from models import Subscription, Tracking, SubscriptionEmail 
from logger import get_logger
# Импортируем утилиты для работы с Excel и почтой
from utils.send_tracking import create_excel_file
from utils.email_sender import send_email 

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time) -> tuple[int, int]:
        """
        Отправляет уведомления пользователям, чьи подписки соответствуют target_time.
        Возвращает (отправлено_сообщений_в_тг, всего_активных_подписок).
        """
        sent_count = 0
        total_active_subscriptions = 0

        # Заголовки для Excel
        EXCEL_HEADERS = [
             'Номер контейнера', 'Станция отправления', 'Станция назначения',
             'Станция операции', 'Операция', 'Дата и время операции',
             'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
             'Номер вагона', 'Дорога операции'
        ]

        logger.info(f"[Notification] Запрос активных подписок на время {target_time.strftime('%H:%M')}...")
        
        async with SessionLocal() as session:
            # 1. Находим все активные подписки на целевое время, включая связи с пользователем и Email.
            result = await session.execute(
                select(Subscription)
                .filter(Subscription.is_active == True)
                .filter(Subscription.notification_time == target_time)
                .options(
                    selectinload(Subscription.user),
                    selectinload(Subscription.target_emails).selectinload(SubscriptionEmail.email)
                ) 
            )
            subscriptions = result.scalars().unique().all()
            total_active_subscriptions = len(subscriptions)
            
            logger.info(f"[Notification] Найдено {total_active_subscriptions} активных подписок для рассылки.")


            for sub in subscriptions:
                if not sub.user or not sub.containers:
                    logger.warning(f"[Notification] Подписка ID {sub.id} пропущена (нет пользователя или контейнеров).")
                    continue
                
                logger.info(f"[Notification] Обработка подписки ID {sub.id} для user {sub.user.telegram_id} ({sub.subscription_name}).")

                # 2. Сбор данных для уведомления (только последний статус)
                container_data_list = []
                excel_rows: List[List[Any]] = [] 
                
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
                        
                        # Собираем данные в формате списка для Excel
                        excel_rows.append([
                             tracking_info.container_number, tracking_info.from_station, tracking_info.to_station,
                             tracking_info.current_station, tracking_info.operation, tracking_info.operation_date,
                             tracking_info.waybill, tracking_info.km_left, tracking_info.forecast_days,
                             tracking_info.wagon_number, tracking_info.operation_road
                        ])
                
                # 3. Форматирование и отправка сообщения в Telegram
                # (Логика Telegram остается прежней и пропускается для краткости)
                if container_data_list:
                    message_parts = [f"🔔 **Отчет по подписке: {sub.subscription_name}** 🔔"]
                    for info in container_data_list:
                        date_str = info.operation_date
                        formatted_date = "н/д"
                        if date_str:
                            try:
                                op_dt = datetime.strptime(date_str, '%d.%m.%Y %H:%M')
                                formatted_date = op_dt.strftime('%d.%m %H:%M')
                            except ValueError:
                                logger.warning(f"[Notification] Не удалось распарсить дату '{date_str}' для контейнера {info.container_number}")
                        
                        message_parts.append(f"*{info.container_number}*: {info.operation} на {info.current_station} ({formatted_date})")
                    
                    try:
                        await self.bot.send_message(
                            chat_id=sub.user.telegram_id,
                            text="\n".join(message_parts),
                            parse_mode="Markdown"
                        )
                        sent_count += 1
                        logger.info(f"🟢 [Notification] Успешно отправлено {len(container_data_list)} статусов пользователю {sub.user.telegram_id}.")
                        
                    except Exception as e:
                        logger.error(f"❌ [Notification] Ошибка отправки пользователю {sub.user.telegram_id}: {e}", exc_info=True)

                    
                    # 4. Проверка и отправка Email/Excel
                    if sub.target_emails and excel_rows:
                        logger.info(f"📬 [Notification] Подписка ID {sub.id} имеет {len(sub.target_emails)} email адресов. Генерация Excel...")
                        
                        # Собираем только подтвержденные email
                        email_recipients = [se.email.email for se in sub.target_emails if se.email.is_verified]
                        
                        # === НОВЫЙ ЛОГ ДЛЯ ОТЛАДКИ ===
                        if sub.target_emails:
                            all_related_emails = [f"{se.email.email} (Verified: {se.email.is_verified})" for se in sub.target_emails]
                            logger.info(f"DEBUG [Email Check] Подписка {sub.id}. Связанные Email: {', '.join(all_related_emails)}. Получатели: {', '.join(email_recipients) if email_recipients else 'NONE'}")
                        # ============================
                        
                        file_path = None
                        try:
                            # Проверяем, есть ли хотя бы один получатель
                            if email_recipients:
                                
                                logger.info(f"DEBUG [Excel Gen] Начинаю генерацию Excel для подписки {sub.id}.") # <-- НОВЫЙ ЛОГ
                                
                                # Генерация Excel в отдельном потоке (т.к. Pandas/openpyxl синхронны)
                                file_path = await asyncio.to_thread(
                                    create_excel_file,
                                    excel_rows,
                                    EXCEL_HEADERS
                                )
                                
                                logger.info(f"DEBUG [Email Send] Начинаю отправку Email с вложением: {os.path.basename(file_path)}.") # <-- НОВЫЙ ЛОГ
                                
                                # Отправка Email в отдельном потоке (т.к. send_email синхронна)
                                await asyncio.to_thread(
                                    send_email,
                                    to=email_recipients,
                                    attachments=[file_path]
                                )
                                logger.info(f"🟢 [Notification] Email успешно отправлен для подписки ID {sub.id}.")
                            else:
                                logger.warning(f"⚠️ [Notification] Подписка ID {sub.id}: Нет подтвержденных получателей Email. Пропуск отправки.")
                                
                        except Exception as e:
                            logger.error(f"❌ [Notification] Ошибка Email/Excel для подписки ID {sub.id}: {e}", exc_info=True)
                        finally:
                            if file_path and os.path.exists(file_path):
                                os.remove(file_path)
                                logger.debug(f"Временный Excel файл {file_path} удален.")
                    
                else:
                    logger.info(f"[Notification] Нет актуальных данных для контейнеров подписки ID {sub.id}.")

        logger.info(f"✅ [Notification] Рассылка завершена. Итого: Отправлено сообщений: {sent_count}, Обработано подписок: {total_active_subscriptions}.")
        
        return sent_count, total_active_subscriptions