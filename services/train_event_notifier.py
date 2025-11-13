# services/train_event_notifier.py
"""
Сервис для обнаружения и логирования событий поезда (прибытие/отправление)
на основе данных дислокации и терминала.
"""
import asyncio 
import os
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from models import TrainEventLog, Tracking
from model.terminal_container import TerminalContainer 
from logger import get_logger

from queries.event_queries import get_global_email_rules 
from utils.email_sender import send_email
from utils.send_tracking import create_excel_file_from_strings # <--- НОВЫЙ ИМПОРТ
from typing import List, Dict, Any, Tuple


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

                    # --- ⭐️ ШАГ 3: Собираем данные о выгрузке в список ⭐️ ---
                    if "выгрузка" in operation_lower:
                        # ✅ ИЗМЕНЕНИЕ: В ЭТОТ СПИСОК МЫ ДОЛЖНЫ ДОБАВЛЯТЬ ТОЛЬКО УНИКАЛЬНЫЕ
                        # Уникальность определяется по ПОЕЗДУ + СТАНЦИИ + ДАТЕ
                        # Для простоты текущей структуры, собираем все, а агрегацию сделаем ниже.
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
                logger.info(f"Обнаружено {len(unload_events_found)} событий 'Выгрузка'. Агрегирую и готовлю Excel.")
                
                # 1. Получаем email-адреса из БД
                recipient_rules = await get_global_email_rules()
                email_list = [rule.recipient_email for rule in recipient_rules if rule.recipient_email]

                if email_list:
                    # 2. Агрегация по Поезду + Станции + Дате
                    aggregated_email_events: Dict[Tuple[str, str, str, datetime.date], Dict[str, Any]] = {}
                    # ... (логика агрегации) ...
                    for event in unload_events_found:
                        key = (event['train'], event['operation'], event['station'], event['time'].date())
                        if key not in aggregated_email_events:
                            aggregated_email_events[key] = {
                                'events': [],
                                'earliest_time': event['time']
                            }
                        aggregated_email_events[key]['events'].append(event)
                        if event['time'] < aggregated_email_events[key]['earliest_time']:
                            aggregated_email_events[key]['earliest_time'] = event['time']
                    
                    # 3. Формируем СВОДНОЕ тело письма (красиво)
                    
                    # --- ✅ НОВОЕ ФОРМАТИРОВАНИЕ ТЕЛА ПИСЬМА ---
                    summary_lines = []
                    sorted_keys = sorted(aggregated_email_events.keys(), key=lambda x: x[0])
                    all_container_numbers = []
                    
                    for train_number, operation, station, _ in sorted_keys:
                        data = aggregated_email_events[(train_number, operation, station, _)]
                        container_count = len(data['events'])
                        earliest_time = data['earliest_time']
                        
                        # Добавляем все контейнеры для последующего сбора данных в Excel
                        all_container_numbers.extend([e['container'] for e in data['events']])
                        
                        summary_lines.append(
                            f"**Поезд:** {train_number}\n"
                            f"**Кол-во контейнеров:** {container_count} шт.\n"
                            f"**Событие:** {operation} на ст. {station}\n"
                            f"**Время (UTC):** {earliest_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"—"
                        )
                    
                    # Форматируем окончательное письмо (HTML/Markdown не поддерживается в send_email)
                    email_subject = f"Сводка по Выгрузке (с Excel): {len(all_container_numbers)} контейнеров"
                    email_body = (
                        f"Здравствуйте!\n\n"
                        f"Обнаружены новые события 'Выгрузка' для контейнеров из {len(aggregated_email_events)} уникальных рейсов.\n\n"
                        f"Сводка:\n"
                        f"{'—' * 30}\n"
                        f"{'\n'.join(summary_lines)}\n"
                        f"{'—' * 30}\n\n"
                        f"Подробная дислокация всех контейнеров находится в приложенном файле Excel.\n\n"
                        f"С уважением,\nВаш контейнерный помощник 🤖"
                    )
                    # --- ✅ КОНЕЦ НОВОГО ФОРМАТИРОВАНИЯ ---
                    
                    # 4. Сбор данных для Excel
                    file_path = None
                    try:
                        # Получаем все последние записи Tracking для найденных контейнеров
                        tracking_data = (await session.execute(
                            select(Tracking).filter(Tracking.container_number.in_(all_container_numbers))
                            .order_by(Tracking.operation_date.desc())
                        )).scalars().all()

                        EXCEL_HEADERS = [
                            'Контейнер', 'Поезд Терминала', 'Станция отправления', 'Станция назначения',
                            'Станция операции', 'Операция', 'Дата и время операции',
                            'Номер вагона'
                        ]
                        excel_rows = []
                        
                        # Получаем номера поездов из TerminalContainer для отображения
                        train_result = await session.execute(
                            select(TerminalContainer.container_number, TerminalContainer.train)
                            .filter(TerminalContainer.container_number.in_(all_container_numbers))
                        )
                        container_to_train = {row[0]: row[1] for row in train_result.all()}

                        for info in tracking_data:
                            # ✅ ИСПОЛЬЗУЕМ _format_dt_for_excel (если импортировали ее из dislocation_handlers)
                            # Если не импортировали, используем простой strftime:
                            formatted_dt = info.operation_date.strftime('%d.%m.%Y %H:%M') if info.operation_date else ''

                            excel_rows.append([
                                info.container_number,
                                container_to_train.get(info.container_number, 'Н/Д'),
                                info.from_station or '', 
                                info.to_station or '',
                                info.current_station or '', 
                                info.operation or '', 
                                formatted_dt,
                                info.wagon_number or ''
                            ])

                        # 5. Генерация Excel-файла
                        file_path = await asyncio.to_thread(
                            create_excel_file_from_strings,
                            excel_rows,
                            EXCEL_HEADERS
                        )

                        # 6. Отправляем ОДНО письмо с вложением
                        await asyncio.to_thread(
                            send_email,
                            to=email_list,
                            subject=email_subject,
                            body=email_body,
                            attachments=[file_path]
                        )
                        logger.info(f"Сводный E-mail о выгрузке {len(all_container_numbers)} контейнеров с Excel успешно отправлен.")
                    except Exception as email_err:
                        logger.error(f"Не удалось отправить СВОДНЫЙ E-mail о выгрузке: {email_err}", exc_info=True)
                    finally:
                        if file_path and os.path.exists(file_path):
                            os.remove(file_path)
            
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