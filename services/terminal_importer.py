import logging
import pandas as pd
import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List

# Настройка логгера
logger = logging.getLogger(__name__)

# Маппинг колонок: Excel заголовок -> Имя поля в БД
COLUMN_MAPPING = {
    'Терминал': 'terminal',
    'Контейнер': 'container_number',
    'Клиент': 'client',
    'ИНН': 'inn',
    'Краткое наименование': 'short_name',
    'Сток': 'stock',
    'Таможенный режим': 'customs_mode',
    'Направление': 'direction',
    'Тип': 'container_type',
    'Размер': 'size',
    'Тара': 'tare',
    'Вес груза (по заявке)': 'weight_client',  # Иногда называется иначе, проверьте точное имя
    'Состояние': 'state',
    'Груз': 'cargo',
    'Пломбы': 'seals',
    'Дата приема': 'accept_date',
    'Время приема': 'accept_time',
    'ID документа (прием)': 'in_id',
    'Вид транспорта (прием)': 'in_transport',
    'Номер ТС/Вагона (прием)': 'in_number',
    'Водитель (прием)': 'in_driver',
    'Текущий статус': 'status'
}

def clean_string_value(val: Any) -> Optional[str]:
    """
    Преобразует значение в строку, корректно обрабатывая числа и float (напр. ИНН).
    Пример: 
        12345 -> "12345"
        12345.0 -> "12345"
        None -> None
    """
    if pd.isna(val) or val == '' or str(val).lower() == 'nan':
        return None
    
    try:
        # Если это float (например 123.0), сначала в int, чтобы убрать .0
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        # Если это int
        if isinstance(val, (int, float)):
            return str(int(val))
    except Exception:
        pass
    
    return str(val).strip()

def parse_date_safe(val: Any) -> Optional[datetime.date]:
    """Безопасный парсинг даты."""
    if pd.isna(val) or val == '':
        return None
    try:
        # Pandas обычно сам парсит в Timestamp, приводим к date
        if isinstance(val, pd.Timestamp):
            return val.date()
        if isinstance(val, datetime.datetime):
            return val.date()
        if isinstance(val, str):
            # Попытка распарсить строку, если pandas не справился
            return pd.to_datetime(val, dayfirst=True).date()
    except Exception as e:
        logger.warning(f"Не удалось распарсить дату '{val}': {e}")
        return None
    return None

def parse_time_safe(val: Any) -> Optional[datetime.time]:
    """Безопасный парсинг времени."""
    if pd.isna(val) or val == '':
        return None
    try:
        if isinstance(val, pd.Timestamp):
            return val.time()
        if isinstance(val, datetime.datetime):
            return val.time()
        if isinstance(val, datetime.time):
            return val
        if isinstance(val, str):
            # Пробуем формат ЧЧ:ММ
            return datetime.datetime.strptime(val[:5], "%H:%M").time()
    except Exception:
        return None
    return None

def parse_float_safe(val: Any) -> Optional[float]:
    """Безопасный парсинг дробного числа."""
    if pd.isna(val) or val == '':
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        # Если строка с запятой (123,45)
        clean_val = str(val).replace(',', '.').replace('\xa0', '').strip()
        return float(clean_val)
    except Exception:
        return None

async def process_terminal_report_file(session: AsyncSession, file_path: str):
    """
    Основная функция обработки файла Excel.
    """
    logger.info(f"[Import] Запуск обработки файла: {file_path}")

    try:
        # 1. Чтение Excel
        # dtype=object заставляет pandas читать все как есть, не пытаясь угадать типы (безопаснее для ИНН)
        df = pd.read_excel(file_path, dtype=object) 
        
        # Переименование колонок для удобства (если имена в файле немного отличаются, можно добавить normalize)
        df.rename(columns=COLUMN_MAPPING, inplace=True)
        
        # Фильтрация только нужных колонок, которые есть в маппинге
        available_columns = [col for col in COLUMN_MAPPING.values() if col in df.columns]
        df = df[available_columns]

        logger.info(f"Таблица загружена ({len(df)} строк). Начинаю подготовку данных...")

        # 2. Подготовка и очистка данных (Data Cleaning)
        # Список полей, которые ОБЯЗАТЕЛЬНО должны быть строками
        str_fields = [
            'terminal', 'container_number', 'client', 'inn', 'short_name', 
            'stock', 'customs_mode', 'direction', 'container_type', 
            'size', 'state', 'cargo', 'seals', 'in_id', 
            'in_transport', 'in_number', 'in_driver', 'status'
        ]
        
        # Список полей с числами
        float_fields = ['tare', 'weight_client']
        
        processed_rows = []

        for index, row in df.iterrows():
            if pd.isna(row.get('container_number')):
                continue  # Пропускаем строки без номера контейнера

            data = {}
            
            # Обработка строковых полей
            for field in str_fields:
                if field in df.columns:
                    data[field] = clean_string_value(row[field])
                else:
                    data[field] = None

            # Обработка числовых полей
            for field in float_fields:
                if field in df.columns:
                    data[field] = parse_float_safe(row[field])
                else:
                    data[field] = None

            # Обработка дат и времени
            data['accept_date'] = parse_date_safe(row.get('accept_date'))
            data['accept_time'] = parse_time_safe(row.get('accept_time'))

            # Добавляем хардкод поля 'terminal', если его нет в файле
            if not data.get('terminal'):
                data['terminal'] = 'A-Terminal'

            processed_rows.append(data)

        logger.info(f"Данные обработаны. Готово к импорту {len(processed_rows)} записей.")

        if not processed_rows:
            logger.warning("Нет данных для импорта после обработки.")
            return

        # 3. Импорт в БД
        # Используем INSERT ... ON CONFLICT (Upsert) или UPDATE
        # Т.к. вы используете "Полную очистку" перед этим, можно использовать обычный INSERT
        # Но для надежности сделаем код, который вставляет данные.
        
        # SQL запрос
        sql = text("""
            INSERT INTO terminal_containers (
                terminal, container_number, client, inn, short_name, stock,
                customs_mode, direction, container_type, size, tare, weight_client,
                state, cargo, seals, accept_date, accept_time,
                in_id, in_transport, in_number, in_driver, status, updated_at
            ) VALUES (
                :terminal, :container_number, :client, :inn, :short_name, :stock,
                :customs_mode, :direction, :container_type, :size, :tare, :weight_client,
                :state, :cargo, :seals, :accept_date, :accept_time,
                :in_id, :in_transport, :in_number, :in_driver, :status, NOW()
            )
            ON CONFLICT (container_number) DO UPDATE SET
                terminal = EXCLUDED.terminal,
                client = EXCLUDED.client,
                inn = EXCLUDED.inn,
                short_name = EXCLUDED.short_name,
                stock = EXCLUDED.stock,
                customs_mode = EXCLUDED.customs_mode,
                direction = EXCLUDED.direction,
                container_type = EXCLUDED.container_type,
                size = EXCLUDED.size,
                tare = EXCLUDED.tare,
                weight_client = EXCLUDED.weight_client,
                state = EXCLUDED.state,
                cargo = EXCLUDED.cargo,
                seals = EXCLUDED.seals,
                accept_date = EXCLUDED.accept_date,
                accept_time = EXCLUDED.accept_time,
                in_id = EXCLUDED.in_id,
                in_transport = EXCLUDED.in_transport,
                in_number = EXCLUDED.in_number,
                in_driver = EXCLUDED.in_driver,
                status = EXCLUDED.status,
                updated_at = NOW();
        """)

        # Выполняем вставку пачками (Batch) для скорости
        batch_size = 1000
        for i in range(0, len(processed_rows), batch_size):
            batch = processed_rows[i:i + batch_size]
            await session.execute(sql, batch)
            await session.commit() # Фиксируем каждую пачку
            logger.info(f"Импортировано {min(i + batch_size, len(processed_rows))} из {len(processed_rows)}")

        logger.info("✅ Импорт успешно завершен.")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка при импорте файла: {e}", exc_info=True)
        raise e  # Пробрасываем ошибку наверх, чтобы manual_importer узнал о ней