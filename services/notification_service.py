# services/notification_service.py
from datetime import time, datetime
import asyncio
import os 
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from typing import List, Any, Dict, Tuple 

from db import SessionLocal
# --- ✅ Добавлен импорт Train ---
from models import Subscription, Tracking, SubscriptionEmail, TrainEventLog, Train
from model.terminal_container import TerminalContainer 
from logger import get_logger
from utils.send_tracking import create_excel_file
from utils.email_sender import send_email 
from services.train_event_notifier import get_unsent_train_events, mark_event_as_sent
from utils.notify import notify_admin

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time) -> tuple[int, int]:
        """
        Отправляет плановые уведомления (09:00, 16:00) пользователям по их подпискам.
        """
        sent_count = 0
        total_active_subscriptions = 0

        # --- ✅ Добавлена колонка 'Станция перегруза' ---
        EXCEL_HEADERS = [
             'Номер контейнера', 'Станция отправления', 'Станция назначения',
             'Станция операции', 'Операция', 'Дата и время операции',
             'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
             'Номер вагона', 'Дорога операции', 'Станция перегруза'
        ]

        logger.info(f"[Notification] Запрос активных подписок на время {target_time.strftime('%H:%M')}...")
        
        async with SessionLocal() as session:
            # 1. Находим все активные подписки на целевое время
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
                        
                        # --- ✅ Получение станции перегруза через Join ---
                        overload_station = ""
                        try:
                            # Ищем станцию перегруза: Container -> TerminalContainer -> Train -> overload_station_name
                            stmt = select(Train.overload_station_name)\
                                   .join(TerminalContainer, TerminalContainer.train == Train.terminal_train_number)\
                                   .where(TerminalContainer.container_number == ctn)
                            
                            train_res = await session.execute(stmt)
                            overload_val = train_res.scalar_one_or_none()
                            if overload_val:
                                overload_station = overload_val
                        except Exception as e:
                             logger.error(f"Ошибка при получении перегруза для {ctn}: {e}")
                        # ------------------------------------------------

                        excel_rows.append([
                             tracking_info.container_number, tracking_info.from_station, tracking_info.to_station,
                             tracking_info.current_station, tracking_info.operation, tracking_info.operation_date,
                             tracking_info.waybill, tracking_info.km_left, tracking_info.forecast_days,
                             tracking_info.wagon_number, tracking_info.operation_road,
                             overload_station # <--- Новая колонка
                        ])
                
                # 3. Форматирование и отправка сообщения в Telegram
                if container_data_list:
                    message_parts = [f"🔔 **Отчет по подписке: {sub.subscription_name}** 🔔"]
                    for info in container_data_list:
                        
                        date_obj = info.operation_date 
                        formatted_date = "н/д"
                        if date_obj: 
                            try:
                                formatted_date = date_obj.strftime('%d.%m %H:%M (UTC)')
                            except Exception as e:
                                logger.warning(f"[Notification] Не удалось отформатировать дату '{date_obj}' для {info.container_number}: {e}")
                        
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
                        
                        email_recipients = [se.email.email for se in sub.target_emails if se.email.is_verified]
                        
                        if sub.target_emails:
                            all_related_emails = [f"{se.email.email} (Verified: {se.email.is_verified})" for se in sub.target_emails]
                            logger.info(f"DEBUG [Email Check] Подписка {sub.id}. Связанные Email: {', '.join(all_related_emails)}. Получатели: {', '.join(email_recipients) if email_recipients else 'NONE'}")
                        
                        file_path = None
                        try:
                            if email_recipients:
                                logger.info(f"DEBUG [Excel Gen] Начинаю генерацию Excel для подписки {sub.id}.") 
                                
                                file_path = await asyncio.to_thread(
                                    create_excel_file,
                                    excel_rows,
                                    EXCEL_HEADERS
                                )
                                
                                logger.info(f"DEBUG [Email Send] Начинаю отправку Email с вложением: {os.path.basename(file_path)}.") 
                                
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

    async def send_aggregated_train_event_notifications(self) -> int:
        """
        Отправляет агрегированные уведомления о НЕЗА_ОТПРАВЛЕННЫХ событиях по поездам.
        Одно уведомление на уникальную комбинацию Поезд + Событие + Станция + ДАТА.
        Отправляет ТОЛЬКО АДМИНУ.
        """
        
        # 1. Получаем все незаотправленные события
        events = await get_unsent_train_events()
        if not events:
            logger.info("[TrainEventNotify] Нет новых событий для отправки админу.")
            return 0
        
        # 2. Группировка событий по уникальному ключу
        # (Поезд, Событие, Станция, ДАТА)
        aggregated_events: Dict[Tuple[str, str, str, datetime.date], Dict[str, Any]] = {}
        
        for event in events:
            # Агрегируем по ДАТЕ, а не по МИНУТЕ
            # (Мы используем .date(), чтобы получить '2025-11-09')
            event_date_key = event.event_time.date() 
            key = (event.train_number, event.event_description, event.station, event_date_key)
            
            if key not in aggregated_events:
                aggregated_events[key] = {
                    'earliest_time': event.event_time, # Запоминаем самое ПЕРВОЕ время
                    'log_ids': [event.id], # Собираем ID всех логов
                    'containers': {event.container_number} # Собираем контейнеры
                }
            else:
                 # Ищем самое раннее время для этого события
                 if event.event_time < aggregated_events[key]['earliest_time']:
                      aggregated_events[key]['earliest_time'] = event.event_time
                 
                 aggregated_events[key]['log_ids'].append(event.id)
                 aggregated_events[key]['containers'].add(event.container_number)
        
        sent_notifications = 0
        
        # 3. Отправляем ОДНО сообщение на КАЖДОЕ УНИКАЛЬНОЕ событие
        async with SessionLocal() as session:
            async with session.begin():
                for (train_number, event_description, station, _), data in aggregated_events.items():
                    
                    log_ids_to_mark = data['log_ids']
                    container_count = len(data['containers'])
                    
                    # 4. Формирование сообщения
                    message_text = (
                        f"🚨 **Обнаружено событие поезда!** 🚨\n\n"
                        f"Поезд: **{train_number}**\n"
                        f"Событие: **{event_description}**\n"
                        f"Станция: **{station}**\n"
                        # Используем самое раннее время из группы
                        f"Время: `{data['earliest_time'].strftime('%d.%m %H:%M (UTC)')}`\n\n"
                        f"*(Касается {container_count} контейнеров)*"
                    )

                    # 5. Отправка уведомления ТОЛЬКО АДМИНУ
                    try:
                        await notify_admin(
                            message_text,
                            silent=True,
                            parse_mode="Markdown"
                        )
                        sent_notifications += 1
                        
                        # 6. Отмечаем ВСЕ логи этого события как отправленные
                        for log_id in log_ids_to_mark:
                             await mark_event_as_sent(log_id, session) 
                        
                    except Exception as e:
                        logger.error(f"[TrainEventNotify] Не удалось уведомить админа или пометить как отправленное: {e}")

            await session.commit() # Коммитим все изменения (пометки 'sent')
            
        logger.info(f"✅ [TrainEventNotify] Рассылка агрегированных событий (только админу) завершена. Отправлено уникальных событий: {sent_notifications}")
        return sent_notifications