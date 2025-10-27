# services/notification_service.py
from datetime import time, datetime
import asyncio
import os 
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import Bot
# Добавлены Dict, Tuple
from typing import List, Any, Dict, Tuple 

from db import SessionLocal
# Импортируем Subscription, Tracking, SubscriptionEmail
from models import Subscription, Tracking, SubscriptionEmail 
# Импортируем TerminalContainer из его файла
from model.terminal_container import TerminalContainer 
from logger import get_logger
# Импортируем утилиты для работы с Excel и почтой
from utils.send_tracking import create_excel_file
from utils.email_sender import send_email 
# КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен импорт для использования оператора .overlap
from sqlalchemy.dialects.postgresql import array_overlap 

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time) -> tuple[int, int]:
        """
        Отправляет уведомления пользователям, чьи подписки соответствуют target_time.
        Возвращает (отправлено_сообщений_в_тг, всего_активных_подписок).
        (Логика осталась прежней, но добавлена для полноты файла)
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
                        
                        if sub.target_emails:
                            all_related_emails = [f"{se.email.email} (Verified: {se.email.is_verified})" for se in sub.target_emails]
                            logger.info(f"DEBUG [Email Check] Подписка {sub.id}. Связанные Email: {', '.join(all_related_emails)}. Получатели: {', '.join(email_recipients) if email_recipients else 'NONE'}")
                        
                        file_path = None
                        try:
                            # Проверяем, есть ли хотя бы один получатель
                            if email_recipients:
                                
                                logger.info(f"DEBUG [Excel Gen] Начинаю генерацию Excel для подписки {sub.id}.") 
                                
                                # Генерация Excel в отдельном потоке (т.к. Pandas/openpyxl синхронны)
                                file_path = await asyncio.to_thread(
                                    create_excel_file,
                                    excel_rows,
                                    EXCEL_HEADERS
                                )
                                
                                logger.info(f"DEBUG [Email Send] Начинаю отправку Email с вложением: {os.path.basename(file_path)}.") 
                                
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

# =========================================================================
# НОВЫЙ МЕТОД ДЛЯ АГРЕГИРОВАННОЙ РАССЫЛКИ СОБЫТИЙ ПОЕЗДА
# =========================================================================
    async def send_aggregated_train_event_notifications(self) -> int:
        """
        Отправляет агрегированные уведомления о незаотправленных событиях по поездам.
        Одно уведомление на уникальную комбинацию Поезд + Событие + Станция + Время.
        """
        # Импорт необходимых функций и моделей (для уменьшения циклической зависимости)
        from services.train_event_notifier import get_unsent_train_events, mark_event_as_sent
        from models import TrainEventLog # Импортируем, если нужно

        # 1. Получаем все незаотправленные события
        events = await get_unsent_train_events()
        if not events:
            logger.info("[TrainEventNotify] Нет новых событий для отправки.")
            return 0
        
        # 2. Группировка событий по уникальному ключу
        aggregated_events: Dict[Tuple[str, str, str, datetime], Dict[str, Any]] = {}
        for event in events:
            # Ключ для агрегации: округляем время до минуты
            event_time_key = event.event_time.replace(second=0, microsecond=0, tzinfo=None)
            key = (event.train_number, event.event_description, event.station, event_time_key)
            
            if key not in aggregated_events:
                aggregated_events[key] = {
                    'earliest_time': event.event_time,
                    'log_ids': [event.id]
                }
            else:
                 if event.event_time < aggregated_events[key]['earliest_time']:
                      aggregated_events[key]['earliest_time'] = event.event_time
                 aggregated_events[key]['log_ids'].append(event.id)
        
        sent_notifications = 0

        for (train_number, event_description, station, _), data in aggregated_events.items():
            
            # 3. Поиск пользователей, отслеживающих контейнеры этого поезда
            user_ids_to_notify = []
            containers_in_train = []
            
            async with SessionLocal() as session:
                 # 3.1. Находим все контейнеры, связанные с этим номером поезда в TerminalContainer
                container_results = await session.execute(
                    select(TerminalContainer.container_number)
                    .where(TerminalContainer.train == train_number)
                )
                containers_in_train = container_results.scalars().all()
                
                # 3.2. Ищем уникальных пользователей, отслеживающих хотя бы один из этих контейнеров
                if containers_in_train:
                    sub_result = await session.execute(
                        select(Subscription.user_telegram_id)
                        # Используем оператор overlap для проверки пересечения списков
                        .where(Subscription.containers.overlap(containers_in_train))
                    )
                    user_ids_to_notify = sub_result.scalars().unique().all()
            
            if not user_ids_to_notify:
                logger.debug(f"[TrainEventNotify] Поезд {train_number} не отслеживается. Пропуск.")
                # Отмечаем логи как отправленные, чтобы не проверять их повторно
                for log_id in data['log_ids']:
                     await mark_event_as_sent(log_id)
                continue

            # 4. Формирование сообщения (одно на поезд/событие)
            message_text = (
                f"🚨 **Обнаружено событие поезда!** 🚨\n\n"
                f"Поезд: **{train_number}**\n"
                f"Событие: **{event_description}**\n"
                f"Станция: **{station}**\n"
                f"Время: `{data['earliest_time'].strftime('%d.%m %H:%M')}`\n\n"
                f"*(Касается {len(containers_in_train)} контейнеров)*"
            )

            # 5. Отправка уведомления и обновление статуса
            for user_id in user_ids_to_notify:
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode="Markdown"
                    )
                    sent_notifications += 1
                except Exception as e:
                    logger.error(f"[TrainEventNotify] Ошибка отправки пользователю {user_id}: {e}")

            # 6. Отмечаем все логи этого события как отправленные
            for log_id in data['log_ids']:
                 await mark_event_as_sent(log_id)
            
        logger.info(f"✅ [TrainEventNotify] Рассылка агрегированных событий поезда завершена.")
        return sent_notifications