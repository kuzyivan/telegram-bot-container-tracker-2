from typing import Optional, Dict, Any
from datetime import datetime

def is_trip_completed(current_station: Optional[str], destination_station: Optional[str], operation: Optional[str]) -> bool:
    """Определяет, завершен ли текущий рейс на основе станции и операции."""
    curr = (current_station or "").strip().lower()
    dest = (destination_station or "").strip().lower()
    op = (operation or "").strip().lower()
    
    if curr and dest and curr == dest:
        # Типичные операции завершения рейса
        if any(x in op for x in ['выгрузка', 'раскредитование', 'выдача']):
            return True
    return False

def is_new_trip(
    old_waybill: Optional[str], 
    new_waybill: Optional[str],
    old_dest_station: Optional[str],
    new_dest_station: Optional[str],
    old_start_date: Optional[datetime],
    new_start_date: Optional[datetime]
) -> bool:
    """Определяет, является ли запись началом нового рейса."""
    new_wb = str(new_waybill or "").strip()
    old_wb = str(old_waybill or "").strip()
    new_dest = str(new_dest_station or "").strip().lower()
    old_dest = str(old_dest_station or "").strip().lower()

    # 1. Сменилась накладная
    if new_wb and old_wb and new_wb != old_wb:
        return True
        
    # 2. Сменилась станция назначения
    if new_dest and old_dest and new_dest != old_dest:
        return True
    
    # 3. Дата начала рейса стала новее
    if new_start_date and old_start_date and new_start_date > old_start_date:
        return True
        
    return False

def should_update_tracking(
    existing_operation_date: Optional[datetime],
    existing_current_station: Optional[str],
    existing_to_station: Optional[str],
    existing_operation: Optional[str],
    existing_waybill: Optional[str],
    existing_trip_start_datetime: Optional[datetime],
    row_data: Dict[str, Any]
) -> bool:
    """
    Основная логика решения: нужно ли обновлять запись в БД.
    Возвращает True, если нужно обновить, False если проигнорировать.
    """
    new_operation_date = row_data.get('operation_date')
    
    # Проверка на завершенность текущего рейса в БД
    completed = is_trip_completed(
        existing_current_station,
        existing_to_station,
        existing_operation
    )

    if completed:
        # Если рейс в БД помечен как завершенный, обновляем только если это НОВЫЙ рейс
        new_trip = is_new_trip(
            old_waybill=existing_waybill,
            new_waybill=row_data.get('waybill'),
            old_dest_station=existing_to_station,
            new_dest_station=row_data.get('to_station'),
            old_start_date=existing_trip_start_datetime,
            new_start_date=row_data.get('trip_start_datetime')
        )
        if not new_trip:
            return False

    # Если рейс не завершен или это новый рейс, проверяем дату операции (чтобы не затереть новым старым)
    # Если даты равны, обычно мы не обновляем, чтобы избежать лишних триггеров, 
    # но в дислокации от РЖД могут быть разные операции в одну минуту.
    # Однако текущая логика в dislocation_importer.py использует STRICTLY > (line 374)
    if new_operation_date and (existing_operation_date is None or new_operation_date > existing_operation_date):
        return True
        
    return False
