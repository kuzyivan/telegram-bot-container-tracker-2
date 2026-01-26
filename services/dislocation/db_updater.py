from typing import List, Dict, Any
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from models import Tracking, TrackingHistory
from queries.train_queries import update_train_status_from_tracking_data
from logger import get_logger 
from services.dislocation.trip_logic import should_update_tracking

logger = get_logger(__name__)

async def update_train_statuses_from_tracking(
    session: AsyncSession, 
    processed_tracking_objects: List[Tracking]
) -> int:
    """
    Агрегирует данные из Tracking и обновляет таблицу 'Train'.
    Логика перенесена из dislocation_importer.py, секция 4.
    """
    # NOTE: Импорт TerminalContainer должен быть внутри функции или перенесен на верхний уровень
    # Но для чистоты зависимостей, импортируем только здесь, чтобы избежать циклической зависимости,
    # если TerminalContainer импортирует что-то из dislocation/
    from model.terminal_container import TerminalContainer 

    logger.info(f"[TrainTable] Запуск обновления статусов поездов для {len(processed_tracking_objects)} записей.")
    
    # 1. Находим последнюю операцию для каждого КОНТЕЙНЕРА из обработанных
    container_latest_op: Dict[str, Tracking] = {}
    for tracking_obj in processed_tracking_objects:
        op_date = tracking_obj.operation_date
        if not op_date:
            continue
            
        container_num = tracking_obj.container_number
        
        # Решаем проблему Pylance: проверяем наличие и дату
        existing_op_date = container_latest_op[container_num].operation_date if container_num in container_latest_op else None
        
        # Обновляем, только если дата новее
        if existing_op_date is None or op_date > existing_op_date:
            container_latest_op[container_num] = tracking_obj
    
    if not container_latest_op:
        logger.info("[TrainTable] Нет данных для обновления статусов поездов.")
        return 0

    # 2. Находим связь Контейнер -> Терминальный Поезд (K25-xxx)
    container_keys = list(container_latest_op.keys())
    result = await session.execute(
        select(TerminalContainer.container_number, TerminalContainer.train)
        .where(TerminalContainer.container_number.in_(container_keys))
        .where(TerminalContainer.train.isnot(None))
    )
    
    # Создаем карту: {'контейнер': 'K25-103'}
    container_to_train_map: Dict[str, str] = {row[0]: row[1] for row in result.all()}

    # 3. Агрегируем по ТЕРМИНАЛЬНОМУ ПОЕЗДУ
    train_latest_op: Dict[str, Tracking] = {}
    
    for container_num, tracking_obj in container_latest_op.items():
        terminal_train_num = container_to_train_map.get(container_num)
        
        if not terminal_train_num:
            continue
            
        if terminal_train_num not in train_latest_op:
            train_latest_op[terminal_train_num] = tracking_obj
        else:
            current_latest_date = train_latest_op[terminal_train_num].operation_date
            if tracking_obj.operation_date and (current_latest_date is None or tracking_obj.operation_date > current_latest_date):
                train_latest_op[terminal_train_num] = tracking_obj

    if not train_latest_op:
        logger.info("[TrainTable] Нет отслеживаемых поездов (K25-xxx) в этом обновлении.")
        return 0

    logger.info(f"[TrainTable] Найдены {len(train_latest_op)} уникальных поездов для обновления: {list(train_latest_op.keys())}")

    # 4. Обновляем таблицу 'Train'
    updated_train_count = 0
    for terminal_train_number, latest_tracking_obj in train_latest_op.items():
        try:
            success = await update_train_status_from_tracking_data(
                terminal_train_number, 
                latest_tracking_obj,
                session=session
            )
            if success:
                updated_train_count += 1
        except Exception as e:
            logger.error(f"[TrainTable] Не удалось обновить статус для поезда {terminal_train_number}: {e}", exc_info=True)

    logger.info(f"[TrainTable] Успешно обновлены статусы для {updated_train_count} поездов.")
    return updated_train_count


async def import_tracking_data_to_db(
    session: AsyncSession, 
    data_rows: List[Dict[str, Any]]
) -> tuple[int, int, List[Tracking]]:
    """
    Обрабатывает строки дислокации: обновляет или вставляет записи в Tracking 
    и добавляет в TrackingHistory.
    Логика перенесена из process_dislocation_file, секция 5.
    """
    updated_count = 0
    inserted_count = 0
    processed_tracking_objects: List[Tracking] = []

    if not data_rows:
        return 0, 0, []

    container_numbers_from_file = [
        row['container_number'] for row in data_rows if row.get('container_number')
    ]
    if not container_numbers_from_file:
        logger.warning("Не найдено ни одной строки с номером контейнера в данных.")
        return 0, 0, []

    # Предварительно загружаем существующие записи Tracking
    existing_trackings = (await session.execute(
        select(Tracking).where(Tracking.container_number.in_(set(container_numbers_from_file)))
    )).scalars().all()
    tracking_map = {t.container_number: t for t in existing_trackings}

    for row_data in data_rows:
        container_number = row_data.get('container_number')
        if not container_number:
            continue

        existing_entry: Tracking = tracking_map.get(container_number) # type: ignore
        new_operation_date = row_data.get('operation_date') 

        if existing_entry:
            # Используем выделенную логику определения необходимости обновления
            if should_update_tracking(
                existing_entry.operation_date,
                existing_entry.current_station,
                existing_entry.to_station,
                existing_entry.operation,
                existing_entry.waybill,
                existing_entry.trip_start_datetime,
                row_data
            ):
                # Обновляем запись
                for key, value in row_data.items():
                    setattr(existing_entry, str(key), value)
                
                updated_count += 1
                processed_tracking_objects.append(existing_entry)

                # Добавляем запись в историю
                if new_operation_date:
                    history_entry = TrackingHistory(
                        container_number=container_number,
                        operation_date=new_operation_date,
                        operation=row_data.get('operation'),
                        current_station=row_data.get('current_station'),
                        operation_road=row_data.get('operation_road'),
                        wagon_number=row_data.get('wagon_number'),
                        train_number=row_data.get('train_number')
                    )
                    # Используем merge, чтобы избежать дубликатов (если unique constraint сработает)
                    await session.merge(history_entry)

        else:
            # Создаем новую запись Tracking
            new_entry_data = {str(k): v for k, v in row_data.items()}
            new_entry = Tracking(**new_entry_data) 
            session.add(new_entry)
            tracking_map[container_number] = new_entry
            
            inserted_count += 1
            processed_tracking_objects.append(new_entry)

            # Добавляем первую запись в историю
            if new_operation_date:
                history_entry = TrackingHistory(
                    container_number=container_number,
                    operation_date=new_operation_date,
                    operation=row_data.get('operation'),
                    current_station=row_data.get('current_station'),
                    operation_road=row_data.get('operation_road'),
                    wagon_number=row_data.get('wagon_number'),
                    train_number=row_data.get('train_number')
                )
                session.add(history_entry)
        
    logger.info(f"[DBUpdater] Сохранено: {inserted_count} новых, {updated_count} обновленных Tracking.")
    
    return inserted_count, updated_count, processed_tracking_objects
