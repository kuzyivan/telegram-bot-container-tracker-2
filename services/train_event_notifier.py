# services/train_event_notifier.py
from collections import defaultdict
from sqlalchemy import select, insert, and_, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Dict

from db import SessionLocal
from models import TrainOperationEvent, TerminalContainer
from utils.notify import notify_admin
from logger import get_logger

logger = get_logger(__name__)

# <<< ИЗМЕНЕНИЕ ЗДЕСЬ >>>
TARGET_OPERATIONS = ["выгрузка", "бросание", "включение"]

async def _get_trains_for_containers(container_numbers: List[str]) -> Dict[str, str]:
    """Эффективно получает номера поездов для списка контейнеров."""
    if not container_numbers:
        return {}
    
    async with SessionLocal() as session:
        result = await session.execute(
            select(TerminalContainer.container_number, TerminalContainer.train)
            .where(TerminalContainer.container_number.in_(container_numbers))
        )
        return {row.container_number: row.train for row in result if row.train}

async def process_dislocation_for_train_events(records: List[Dict]):
    """
    Анализирует все записи из файла дислокации и отправляет уведомления о новых событиях поезда.
    """
    # 1. Фильтруем только интересующие нас операции
    target_records = [
        rec for rec in records
        if any(op in rec.get("operation", "").lower() for op in TARGET_OPERATIONS)
    ]
    if not target_records:
        return

    # 2. Получаем номера поездов для всех найденных контейнеров одним запросом
    container_to_train = await _get_trains_for_containers([r["container_number"] for r in target_records])

    # 3. Группируем события по уникальному ключу (поезд, операция, станция, дата)
    unique_events = {}
    for rec in target_records:
        train = container_to_train.get(rec["container_number"])
        if not train:
            continue
        
        event_key = (
            train,
            rec["operation"],
            rec["current_station"],
            rec["operation_date"]
        )
        
        if event_key not in unique_events:
            unique_events[event_key] = rec # Сохраняем первую запись, которая сформировала событие

    if not unique_events:
        logger.info("Найдены целевые операции, но не удалось определить поезда. Уведомления не отправлены.")
        return

    # 4. Проверяем, о каких событиях мы уже уведомляли
    async with SessionLocal() as session:
        # Собираем ключи для запроса к БД
        event_filters = []
        for train, op, station, date in unique_events.keys():
            event_filters.append(
                and_(
                    TrainOperationEvent.train_number == train,
                    TrainOperationEvent.operation == op,
                    TrainOperationEvent.station == station,
                    TrainOperationEvent.operation_date == date
                )
            )
        
        # Выполняем запрос, чтобы найти уже существующие события
        if event_filters:
            existing_events_query = select(TrainOperationEvent).where(or_(*event_filters))
            existing_events_result = await session.execute(existing_events_query)
            existing_events = {(e.train_number, e.operation, e.station, e.operation_date) for e in existing_events_result.scalars().all()}
        else:
            existing_events = set()


    # 5. Отправляем уведомления только о новых событиях
    new_events_to_notify = []
    for key, record_data in unique_events.items():
        if key not in existing_events:
            new_events_to_notify.append(record_data)
            
    if not new_events_to_notify:
        logger.info("Все найденные события по поездам уже были отправлены ранее.")
        return

    logger.info(f"Обнаружено {len(new_events_to_notify)} новых событий по поездам. Отправка уведомлений...")
    
    for rec in new_events_to_notify:
        train = container_to_train.get(rec["container_number"], "неизвестен")
        message = (
            f"📦 *Контейнер*: `{rec['container_number']}` (как представитель поезда)\n"
            f"🚂 *Поезд*: `{train}`\n\n"
            f"🛤 *Маршрут*:\n`{rec.get('from_station', 'N/A')}` 🚂 → `{rec.get('to_station', 'N/A')}`\n\n"
            f"📍 *Текущая станция*: {rec.get('current_station', 'N/A')} 🛤️ ({rec.get('operation_road', 'N/A')})\n"
            f"📅 *Последняя операция*:\n{rec.get('operation_date', 'N/A')} — _{rec.get('operation', 'N/A')}_"
        )
        await notify_admin(message, silent=False)

    # 6. Сохраняем информацию о том, что мы отправили уведомления
    async with SessionLocal() as session:
        new_event_rows = [
            {
                "train_number": container_to_train.get(rec["container_number"]),
                "operation": rec["operation"],
                "station": rec["current_station"],
                "operation_date": rec["operation_date"]
            }
            for rec in new_events_to_notify if container_to_train.get(rec["container_number"])
        ]
        if new_event_rows:
            try:
                await session.execute(insert(TrainOperationEvent), new_event_rows)
                await session.commit()
            except IntegrityError:
                logger.warning("Произошла попытка повторной записи события поезда, которая была предотвращена БД.")
                await session.rollback()