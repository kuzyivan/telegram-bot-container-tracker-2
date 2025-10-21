# services/train_event_notifier.py
"""
Сервис для обнаружения и логирования событий поезда (прибытие/отправление)
на основе данных дислокации и терминала.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db import SessionLocal
from models import TrainEventLog # Импортируем только то, что есть в models.py
from model.terminal_container import TerminalContainer # Импортируем TerminalContainer из его файла
from logger import get_logger

logger = get_logger(__name__)

# Константы для целевых операций
TARGET_OPERATIONS = ["выгрузка", "бросание", "включение"] # Добавьте/измените операции при необходимости

async def log_train_event(session: SessionLocal, container_number: str, train_number: str,
                          event_description: str, station: str, event_time: datetime):
    """Логирует событие поезда в базу данных, избегая дубликатов."""

    # Проверка на дубликат (по контейнеру, поезду, событию и станции за последние N часов, например)
    # Это предотвратит повторное логирование одного и того же события при частых обновлениях
    # existing_event = await session.execute(
    #     select(TrainEventLog).filter(
    #         TrainEventLog.container_number == container_number,
    #         TrainEventLog.train_number == train_number,
    #         TrainEventLog.event_description == event_description,
    #         TrainEventLog.station == station,
    #         TrainEventLog.event_time > datetime.now() - timedelta(hours=6) # Пример окна дедупликации
    #     ).limit(1)
    # )
    # if existing_event.scalar_one_or_none():
    #     logger.info(f"Событие для {container_number} ({event_description} на {station}) уже залогировано.")
    #     return

    log_entry = TrainEventLog(
        container_number=container_number,
        train_number=train_number,
        event_description=event_description,
        station=station,
        event_time=event_time
        # notification_sent_at пока не ставим, это сделает сервис уведомлений
    )
    session.add(log_entry)
    logger.info(f"Залогировано событие: {container_number}, Поезд: {train_number}, Событие: {event_description}, Станция: {station}")


async def process_dislocation_for_train_events(dislocation_records: list[dict]):
    """
    Анализирует записи дислокации на предмет событий поезда и логирует их.
    """
    logger.info(f"Начинаю анализ {len(dislocation_records)} записей дислокации на события поезда...")
    processed_count = 0
    async with SessionLocal() as session:
        async with session.begin(): # Используем одну транзакцию для всех логов

            # Получаем все контейнеры с терминала, у которых есть номер поезда
            result = await session.execute(
                select(TerminalContainer)
                # УДАЛЯЕМ selectinload(TerminalContainer.user) - это источник ошибки
                .filter(TerminalContainer.train != None, TerminalContainer.train != '')
            )
            terminal_containers_map = {tc.container_number: tc for tc in result.scalars().all()}

            if not terminal_containers_map:
                logger.warning("Не найдено контейнеров с номерами поездов на терминале. Анализ событий невозможен.")
                return

            for record in dislocation_records:
                container_number = record.get("container_number")
                operation = record.get("operation", "").lower().strip()
                station = record.get("current_station")
                operation_date_str = record.get("operation_date")

                terminal_info = terminal_containers_map.get(container_number)

                # Проверяем, есть ли этот контейнер на терминале и назначен ли ему поезд
                if not terminal_info or not terminal_info.train:
                    continue # Этот контейнер не отслеживается по поезду

                # Проверяем, входит ли операция в список целевых
                is_target_operation = any(op in operation for op in TARGET_OPERATIONS)

                if is_target_operation and station and operation_date_str:
                    try:
                        # Преобразуем строку времени в datetime
                        # УБЕДИТЕСЬ, что формат 'DD.MM.YYYY HH24:MI' СООТВЕТСТВУЕТ вашим данным!
                        event_time = datetime.strptime(operation_date_str, '%d.%m.%Y %H:%M')
                    except ValueError:
                        logger.warning(f"Не удалось распознать дату '{operation_date_str}' для контейнера {container_number}. Пропускаю.")
                        continue

                    # Формируем описание события
                    event_description = f"Операция '{record.get('operation')}' на станции" # Используем оригинальное название операции

                    # Логируем событие
                    await log_train_event(
                        session=session,
                        container_number=container_number,
                        train_number=terminal_info.train,
                        event_description=event_description,
                        station=station,
                        event_time=event_time
                    )
                    processed_count += 1

        # Коммит транзакции произойдет автоматически после выхода из `async with session.begin()`

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

async def mark_event_as_sent(event_id: int):
    """Отмечает событие как отправленное."""
    async with SessionLocal() as session:
        async with session.begin():
            event = await session.get(TrainEventLog, event_id)
            if event:
                event.notification_sent_at = datetime.now()
                await session.commit()