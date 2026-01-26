from typing import Dict, List

# =========================================================================
# === 1. КАРТА СОПОСТАВЛЕНИЯ КОЛОНОК RZD (из dislocation_importer.py) ===
# =========================================================================

COLUMN_MAPPING_RZD_NEW: Dict[str, str] = {
    'Номер контейнера': 'container_number',
    'Номер накладной': 'waybill',
    'Тип контейнера': 'container_type',
    'Дата и время начала рейса': 'trip_start_datetime',
    'Государство отправления': 'from_state',
    'Станция отправления': 'from_station',
    'Дорога отправления': 'from_road',
    'Дата и время окончания рейса': 'trip_end_datetime',
    'Страна назначения': 'to_country',
    'Дорога назначения': 'to_road',
    'Станция назначения': 'to_station',
    'Грузоотправитель (ТГНЛ)': 'sender_tgnl',
    'Грузоотправитель': 'sender_name_short',
    'Грузоотправитель (ОКПО)': 'sender_okpo',
    'Грузоотправитель (наим)': 'sender_name',
    'Грузополучатель (ТГНЛ)': 'receiver_tgnl',
    'Грузополучатель': 'receiver_name_short',
    'Грузополучатель (ОКПО)': 'receiver_okpo',
    'Грузополучатель (наим)': 'receiver_name',
    'Наименование груза': 'cargo_name',
    'Код груза ГНГ': 'cargo_gng_code',
    'Вес груза (кг)': 'cargo_weight_kg',
    'Станция операции': 'current_station',
    'Операция': 'operation',
    'Дорога операции': 'operation_road',
    'Мнемокод операции': 'operation_mnemonic',
    'Дата и время операции': 'operation_date',
    'Состояние контейнера': 'container_state',
    'Индекс поезда с наименованиями станций': 'train_index_full',
    'Номер поезда': 'train_number',
    'Номер вагона': 'wagon_number',
    'Количество пломб': 'seals_count',
    'Государство приема': 'accept_state',
    'Государство сдачи': 'surrender_state',
    'Дорога приема': 'accept_road',
    'Дорога сдачи': 'surrender_road',
    'Нормативный срок доставки': 'delivery_deadline',
    'Расстояние общее': 'total_distance',
    'Расстояние пройденное': 'distance_traveled',
    'Расстояние оставшееся': 'km_left',
    'Время простоя под последней операцией (сутки:часы:минуты)': 'last_op_idle_time_str',
    'Время простоя под последней операцией (сутки)': 'last_op_idle_days',
    'Идентификатор отправки': 'dispatch_id',
    'Идентификатор накладной': 'waybill_id',
    'Признак груж. рейса': 'is_loaded_trip',
}

# =========================================================================
# === 2. КОНСТАНТЫ ПАРСИНГА И ФИЛЬТРЫ (из dislocation_importer.py) ===
# =========================================================================

# Список строковых колонок, которые нужно привести к строке (удалить .0)
STRING_COLS_TO_CONVERT: List[str] = [
    'sender_tgnl', 'sender_okpo', 'sender_name',
    'receiver_tgnl', 'receiver_okpo', 'receiver_name',
    'cargo_gng_code', 'train_number', 'wagon_number', 'waybill',
    'dispatch_id', 'sender_name_short', 'receiver_name_short',
    'train_index_full'
]

# Колонки Excel, которые должны быть считаны как str, чтобы избежать потери ведущих нулей
EXCEL_COLS_AS_STR: List[str] = [
    'Грузоотправитель (ТГНЛ)', 'Грузоотправитель (ОКПО)', 'Грузоотправитель (наим)',
    'Грузополучатель (ТГНЛ)', 'Грузополучатель (ОКПО)', 'Грузополучатель (наим)',
    'Код груза ГНГ', 'Номер поезда', 'Номер вагона', 'Номер накладной',
    'Идентификатор отправки', 'Грузоотправитель', 'Грузополучатель',
    'Индекс поезда с наименованиями станций'
]

# Форматы дат
DT_FORMAT_WITH_TIME = '%d.%m.%Y %H:%M'
DT_FORMAT_DATE_ONLY = '%d.%m.%Y'

# Фильтры для ImapService
SUBJECT_FILTER_DISLOCATION = r'Отчёт\s+слежения\s+TrackerBot\s*№'
SENDER_FILTER_DISLOCATION = 'cargolk@gvc.rzd.ru'
FILENAME_PATTERN_DISLOCATION = r'\.(xlsx|xls)$'
DOWNLOAD_DIR = "downloads"
