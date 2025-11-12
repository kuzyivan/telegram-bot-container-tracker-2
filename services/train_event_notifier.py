# services/train_event_notifier.py
"""
Сервис для обнаружения и логирования событий поезда (прибытие/отправление)
на основе данных дислокации и терминала.
"""
import asyncio 
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from models import TrainEventLog 
from model.terminal_container import TerminalContainer 
from logger import get_logger

from queries.event_queries import get_global_email_rules 
from utils.email_sender import send_email
from typing import List, Dict, Any # <-- ✅ Добавлен импорт


logger = get_logger(__name__)

# Константы для целевых операций (приводим к lower() для сравнения)
TARGET_OPERATIONS = [
    "выгрузка", 
    "бросание", 
    "включение", 
    "погрузка",
    "исключение" # Добавлено
] 

async def log_train_event(session: AsyncSession, container_number: str, train_number: str,
                          event_description: str, station: str, event_time: datetime):
    """Логирует событие поезда в базу данных, избегая дубликатов."""

    existing_event = await session.execute(
        select(TrainEventLog).filter(
            TrainEventLog.container_number == container_number,
            TrainEventLog.event_description == event_description,
            TrainEventLog.station == station,
            TrainEventLog.event_time == event_time
        ).limit(1)
    )
    
    if existing_event.scalar_one_or_none():
        logger.debug(f"[Dedup] Событие для {container_number} ({event_description} на {station}) уже залогировано. Пропуск.")
        return False # Не добавлено

    log_entry = TrainEventLog(
        container_number=container_number,
        train_number=train_number,
        event_description=event_description,
        station=station,
        event_time=event_time
    )
    session.add(log_entry)
    logger.info(f"Залогировано НОВОЕ событие: {container_number}, Поезд: {train_number}, Событие: {event_description}, Станция: {station}")
    return True # Добавлено


async def process_dislocation_for_train_events(dislocation_records: list[dict]):
    """
    Анализирует записи дислокации на предмет событий поезда и логирует их.
    """
    logger.info(f"Начинаю анализ {len(dislocation_records)} записей дислокации на события поезда...")
    processed_count = 0
    
    # --- ⭐️ ШАГ 1: Создаем пустой список для сбора событий ⭐️ ---
    unload_events_found: List[Dict[str, Any]] = []
    
    async with SessionLocal() as session:
        async with session.begin(): # Используем одну транзакцию для всех логов

            # Получаем все контейнеры с терминала, у которых есть номер поезда
            result = await session.execute(
                select(TerminalContainer)
                .filter(TerminalContainer.train != None, TerminalContainer.train != '')
            )
            terminal_containers_map = {tc.container_number: tc for tc in result.scalars().all()}

            if not terminal_containers_map:
                logger.warning("Не найдено контейнеров с номерами поездов на терминале. Анализ событий невозможен.")
                return

            for record in dislocation_records:
                container_number = record.get("container_number")
                operation_raw = record.get("operation", "").strip()
                operation_lower = operation_raw.lower()
                station = record.get("current_station")
                operation_date_dt = record.get("operation_date") # Это уже datetime

                terminal_info = terminal_containers_map.get(container_number)

                if not terminal_info or not terminal_info.train:
                    continue 

                # Проверяем, входит ли операция в список целевых
                is_target_operation = any(op in operation_lower for op in TARGET_OPERATIONS)

                if is_target_operation and station and operation_date_dt:
                    
                    # Формируем описание события
                    event_description = f"Операция '{operation_raw}'" # Используем оригинальное название операции

                    # --- ⭐️ ШАГ 2: Логика отправки E-mail УДАЛЕНА отсюда ⭐️ ---
                    
                    # --- ⭐️ ШАГ 3: Собираем данные о выгрузке в список ⭐️ ---
                    if "выгрузка" in operation_lower:
                        unload_events_found.append({
                            "container": container_number,
                            "train": terminal_info.train,
                            "operation": operation_raw,
                            "station": station,
                            "time": operation_date_dt
                        })

                    # Логируем событие (с дедупликацией)
                    added = await log_train_event(
                        session=session,
                        container_number=container_number,
                        train_number=terminal_info.train,
                        event_description=event_description,
                        station=station,
                        event_time=operation_date_dt # Передаем datetime
                    )
                    if added:
                        processed_count += 1
            
            # --- ⭐️ ШАГ 4: Отправляем ОДНО письмо (ПОСЛЕ цикла) ⭐️ ---
            if unload_events_found:
                logger.info(f"Обнаружено {len(unload_events_found)} событий 'Выгрузка'. Агрегирую в одно E-mail сообщение.")
                
                # 1. Получаем email-адреса из БД
                recipient_rules = await get_global_email_rules()
                email_list = [rule.recipient_email for rule in recipient_rules if rule.recipient_email]

                if email_list:
                    # 2. Формируем ОДНО большое письмо
                    email_subject = f"Сводка по Выгрузке: {len(unload_events_found)} контейнеров"
                    body_lines = [
                        "Здравствуйте,", 
                        "", 
                        f"Обнаружены события 'Выгрузка' для следующих контейнеров:"
                    ]
                    
                    # Сортируем по поезду, потом по контейнеру для удобства
                    sorted_events = sorted(unload_events_found, key=lambda x: (x['train'], x['container']))
                    
                    for event in sorted_events:
                        body_lines.append(
                            f"• **{event['container']}** (Поезд: {event['train']}) - {event['operation']} на ст. {event['station']} ({event['time'].strftime('%d.%m %H:%M')})"
                        )
                    
                    email_body = "\n".join(body_lines)
                    
                    # 3. Отправляем ОДНО письмо
                    try:
                        await asyncio.to_thread(
                            send_email,
                            to=email_list,
                            subject=email_subject,
                            body=email_body,
                            attachments=None
                        )
                        logger.info(f"Сводный E-mail о выгрузке {len(unload_events_found)} контейнеров успешно отправлен.")
                    except Exception as email_err:
                        logger.error(f"Не удалось отправить СВОДНЫЙ E-mail о выгрузке: {email_err}", exc_info=True)
                else:
                    logger.info("События 'Выгрузка' обнаружены, но в БД нет E-mail получателей.")
            
            # --- ⭐️ КОНЕЦ НОВОЙ ЛОГИКИ ⭐️ ---
                
        # Коммит транзакции 
        await session.commit()

    if processed_count == 0:
        logger.info("Новых событий по поездам в данных дислокации не найдено.")
    else:
         logger.info(f"Анализ событий поезда завершен. Залогировано {processed_count} новых событий.")
         
async def get_unsent_train_events() -> list[TrainEventLog]:
    """Получает все незаотправленные события по поездам."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrainEventLog)
            .filter(TrainEventLog.notification_sent_at == None)
            .order_by(TrainEventLog.event_time) # Сначала отправляем старые события
        )
        events = result.scalars().all()
        return list(events)

async def mark_event_as_sent(event_id: int, session: AsyncSession):
    """
    Отмечает событие как отправленное.
    ВАЖНО: Ожидает ВНЕШНЮЮ сессию.
    """
    event = await session.get(TrainEventLog, event_id)
    if event:
        event.notification_sent_at = datetime.now()