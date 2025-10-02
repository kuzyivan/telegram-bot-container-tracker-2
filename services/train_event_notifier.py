# services/train_event_notifier.py
from sqlalchemy import select, insert, and_, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Dict

from db import SessionLocal
from models import TrainOperationEvent, TerminalContainer
from utils.notify import notify_admin
from logger import get_logger

logger = get_logger(__name__)

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
    target_records = [
        rec for rec in records
        if any(op in rec.get("operation", "").lower() for op in TARGET_OPERATIONS)
    ]
    if not target_records:
        return

    container_to_train = await _get_trains_for_containers([r["container_number"] for r in target_records])

    unique_events = {}
    for rec in target_records:
        train = container_to_train.get(rec["container_number"])
        if not train:
            continue
        
        op_text = rec["operation"].lower()
        op_type = "неизвестно"
        if "выгрузка" in op_text:
            op_type = "выгрузка"
        elif "бросание" in op_text:
            op_type = "бросание"
        elif "включение" in op_text:
            op_type = "включение"

        date_only = rec["operation_date"].split(' ')[0]

        event_key = (train, op_type, rec["current_station"], date_only)
        
        if event_key not in unique_events:
            unique_events[event_key] = rec

    if not unique_events:
        return

    async with SessionLocal() as session:
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
        
        if event_filters:
            existing_events_query = select(TrainOperationEvent).where(or_(*event_filters))
            existing_events_result = await session.execute(existing_events_query)
            existing_events = {(e.train_number, e.operation, e.station, e.operation_date) for e in existing_events_result.scalars().all()}
        else:
            existing_events = set()

    new_events_to_notify_keys = []
    for key in unique_events.keys():
        if key not in existing_events:
            new_events_to_notify_keys.append(key)
            
    if not new_events_to_notify_keys:
        logger.info("Все найденные события по поездам уже были отправлены ранее.")
        return

    logger.info(f"Обнаружено {len(new_events_to_notify_keys)} новых событий по поездам. Отправка уведомлений...")
    
    for key in new_events_to_notify_keys:
        rec = unique_events[key]
        train = key[0]
        
        title = "❗️🔔 *НОВЫЙ СТАТУС ПОЕЗДА* 🔔❗️\n\n"
        message = (
            title +
            f"📦 *Контейнер*: `{rec['container_number']}` (как представитель поезда)\n"
            f"🚂 *Поезд*: `{train}`\n\n"
            f"🛤 *Маршрут*:\n`{rec.get('from_station', 'N/A')}` 🚂 → `{rec.get('to_station', 'N/A')}`\n\n"
            f"📍 *Текущая станция*: `{rec.get('current_station', 'N/A')}` 🛤️ ({rec.get('operation_road', 'N/A')})\n"
            f"📅 *Последняя операция*:\n{rec.get('operation_date', 'N/A')} — _{rec.get('operation', 'N/A')}_"
        )
        await notify_admin(message, silent=False) # Вызываем без parse_mode, используется Markdown по умолчанию

    async with SessionLocal() as session:
        new_event_rows = [
            {"train_number": key[0], "operation": key[1], "station": key[2], "operation_date": key[3]}
            for key in new_events_to_notify_keys
        ]
        if new_event_rows:
            try:
                await session.execute(insert(TrainOperationEvent), new_event_rows)
                await session.commit()
            except IntegrityError:
                logger.warning("Произошла попытка повторной записи события поезда, которая была предотвращена БД.")
                await session.rollback()