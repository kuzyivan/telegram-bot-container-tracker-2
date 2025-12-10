import logging
import pandas as pd
import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List

# Настройка логгера
logger = logging.getLogger(__name__)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОЧИСТКИ ---

def clean_string_value(val: Any) -> Optional[str]:
    """Преобразует значение в строку, корректно обрабатывая числа и float (напр. ИНН)."""
    if pd.isna(val) or val == '' or str(val).lower() == 'nan':
        return None
    try:
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
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
        if isinstance(val, pd.Timestamp):
            return val.date()
        if isinstance(val, datetime.datetime):
            return val.date()
        if isinstance(val, str):
            return pd.to_datetime(val, dayfirst=True).date()
    except Exception:
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
            return datetime.datetime.strptime(val[:5], "%H:%M").time()
    except Exception:
        return None
    return None

def parse_float_safe(val: Any) -> Optional[float]:
    """Безопасный парсинг числа."""
    if pd.isna(val) or val == '':
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        clean_val = str(val).replace(',', '.').replace('\xa0', '').strip()
        return float(clean_val)
    except Exception:
        return None

# --- ЛОГИКА ОБРАБОТКИ ---

async def process_terminal_report_file(session: AsyncSession, file_path: str):
    """
    Главная функция. Открывает Excel и ищет нужные листы (Arrival, Dispatch).
    """
    logger.info(f"[Import] Анализ файла: {file_path}")

    try:
        # Получаем объект ExcelFile, чтобы прочитать имена листов
        xls = pd.ExcelFile(file_path)
        sheet_names = xls.sheet_names
        logger.info(f"Найдены листы: {sheet_names}")

        processed_any = False

        # 1. Ищем лист ARRIVAL (Прибытие)
        arrival_sheet = next((s for s in sheet_names if "Arrival" in s), None)
        if arrival_sheet:
            logger.info(f"Обработка листа ПРИБЫТИЯ: {arrival_sheet}")
            df_arrival = pd.read_excel(xls, sheet_name=arrival_sheet, dtype=object)
            await _process_arrival_data(session, df_arrival)
            processed_any = True
        else:
            logger.warning("Лист 'Arrival' не найден в файле.")

        # 2. Ищем лист DISPATCH (Отгрузка)
        dispatch_sheet = next((s for s in sheet_names if "Dispatch" in s), None)
        if dispatch_sheet:
            logger.info(f"Обработка листа ОТГРУЗКИ: {dispatch_sheet}")
            df_dispatch = pd.read_excel(xls, sheet_name=dispatch_sheet, dtype=object)
            await _process_dispatch_data(session, df_dispatch)
            processed_any = True
        else:
            logger.warning("Лист 'Dispatch' не найден в файле.")
        
        # Если специфичные листы не найдены, пробуем обработать первый лист как общий (fallback)
        if not processed_any:
            logger.warning("Специфичные листы не найдены. Пробуем обработать первый лист как общий сток.")
            df_generic = pd.read_excel(xls, sheet_name=0, dtype=object)
            await _process_arrival_data(session, df_generic)

        logger.info("✅ Обработка файла завершена.")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка при обработке Excel: {e}", exc_info=True)
        raise e

async def _process_arrival_data(session: AsyncSession, df: pd.DataFrame):
    """
    Обработка данных о ПРИБЫТИИ (Arrival).
    Вставка новых контейнеров или обновление существующих (UPSERT).
    """
    # Нормализация имен колонок (удаляем пробелы по краям)
    df.columns = df.columns.str.strip()
    
    # Маппинг для Arrival (стандартный набор)
    # Excel Column -> DB Field
    mapping = {
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
        'Брутто клиента': 'weight_client', # Или 'Вес груза (по заявке)'
        'Состояние': 'state',
        'Груз': 'cargo',
        'Пломбы': 'seals',
        'Принят': 'accept_date',       # Дата/Время приема
        # Поля "ВХОДА" (первая группа транспортных полей)
        'Id': 'in_id',
        'Транспорт': 'in_transport',
        'Номер вагона | Номер тягача': 'in_number',
        'Станция | Водитель': 'in_driver'
    }

    processed_rows = []
    
    for _, row in df.iterrows():
        if pd.isna(row.get('Контейнер')):
            continue

        data = {}
        # Заполняем данные по маппингу
        for xls_col, db_col in mapping.items():
            val = row.get(xls_col)
            
            # Специфичная обработка типов
            if db_col in ['tare', 'weight_client']:
                data[db_col] = parse_float_safe(val)
            elif db_col == 'accept_date':
                # В файле Arrival поле 'Принят' содержит дату и время
                data['accept_date'] = parse_date_safe(val)
                data['accept_time'] = parse_time_safe(val)
            else:
                data[db_col] = clean_string_value(val)

        # Хардкод и статусы
        if not data.get('terminal'):
            data['terminal'] = 'A-Terminal'
        
        data['status'] = 'ARRIVED' # Ставим статус "Прибыл"
        
        processed_rows.append(data)

    if processed_rows:
        await _bulk_upsert_arrival(session, processed_rows)

async def _process_dispatch_data(session: AsyncSession, df: pd.DataFrame):
    """
    Обработка данных об ОТГРУЗКЕ (Dispatch).
    Только ОБНОВЛЕНИЕ существующих контейнеров (добавление даты убытия).
    """
    df.columns = df.columns.str.strip()

    # В листе Dispatch есть дублирующиеся колонки (Id, Транспорт и т.д.)
    # Pandas при чтении добавляет суффикс .1 ко вторым экземплярам.
    # Первые экземпляры - это ПРИЕМ, Вторые (.1) - это ОТПРАВКА.
    
    # Ищем колонку "Отправлен"
    if 'Отправлен' not in df.columns:
        logger.warning("В листе Dispatch нет колонки 'Отправлен'. Пропуск.")
        return

    processed_rows = []

    for _, row in df.iterrows():
        cont_num = clean_string_value(row.get('Контейнер'))
        if not cont_num:
            continue

        # Собираем данные для обновления ВЫХОДА
        data = {
            'container_number': cont_num,
            'status': 'DISPATCHED',
            'updated_at': datetime.datetime.now()
        }

        # Дата убытия
        out_date_val = row.get('Отправлен')
        data['leave_date'] = parse_date_safe(out_date_val)
        data['leave_time'] = parse_time_safe(out_date_val)

        # Поля "ВЫХОДА" (обычно имеют суффикс .1 в Pandas, если заголовки дублируются)
        # Если заголовки уникальны, нужно смотреть на файл. 
        # В твоем файле Dispatch заголовки: Принят, Id, Транспорт ... Отправлен, Id, Транспорт
        # Значит в Pandas это будет: Id (вход), Id.1 (выход)
        
        data['out_id'] = clean_string_value(row.get('Id.1')) # Id отправки
        data['out_transport'] = clean_string_value(row.get('Транспорт.1'))
        data['out_number'] = clean_string_value(row.get('Номер вагона | Номер тягача.1'))
        data['out_driver'] = clean_string_value(row.get('Станция | Водитель.1'))
        
        # Если вдруг Pandas не добавил .1 (заголовки уникальны), пробуем без суффикса
        if not data['out_id'] and 'Id' in row and row.get('Отправлен'):
             # Это сложный кейс, надеемся на .1, так как заголовки точно дублируются
             pass

        processed_rows.append(data)

    if processed_rows:
        await _bulk_update_dispatch(session, processed_rows)

# --- SQL ЗАПРОСЫ ---

async def _bulk_upsert_arrival(session: AsyncSession, rows: List[dict]):
    """SQL для вставки/обновления прибывших."""
    if not rows:
        return
    
    stmt = text("""
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
            stock = EXCLUDED.stock,
            state = EXCLUDED.state,
            accept_date = EXCLUDED.accept_date,
            accept_time = EXCLUDED.accept_time,
            in_transport = EXCLUDED.in_transport,
            in_number = EXCLUDED.in_number,
            in_driver = EXCLUDED.in_driver,
            status = EXCLUDED.status,
            updated_at = NOW();
    """)
    
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        await session.execute(stmt, rows[i:i + batch_size])
        await session.commit()
    logger.info(f"💾 Обработано {len(rows)} записей (Arrival).")

async def _bulk_update_dispatch(session: AsyncSession, rows: List[dict]):
    """SQL для обновления убывших."""
    if not rows:
        return

    # Используем временную таблицу или CASE для массового обновления, 
    # но для простоты в SQLAlchemy async часто проще обновить в цикле или через executemany
    # Здесь используем executemany update
    
    stmt = text("""
        UPDATE terminal_containers
        SET 
            status = :status,
            leave_date = :leave_date,
            leave_time = :leave_time,
            out_id = :out_id,
            out_transport = :out_transport,
            out_number = :out_number,
            out_driver = :out_driver,
            updated_at = NOW()
        WHERE container_number = :container_number
    """)
    
    # Для UPDATE batch execution работает эффективно
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        await session.execute(stmt, rows[i:i + batch_size])
        await session.commit()
    logger.info(f"🚚 Обновлено {len(rows)} записей (Dispatch).")