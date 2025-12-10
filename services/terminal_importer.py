import logging
import pandas as pd
import datetime
import os
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

# --- Импорты для работы с почтой и БД ---
from db import SessionLocal
from services.imap_service import ImapService
from imap_tools.query import AND

# Настройка логгера
logger = logging.getLogger(__name__)

# Папка для загрузок
TERMINAL_DOWNLOAD_FOLDER = "download_container"
os.makedirs(TERMINAL_DOWNLOAD_FOLDER, exist_ok=True)

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

def _get_vladivostok_date_str(days_offset: int = 0) -> str:
    """Возвращает дату во Владивостоке в формате ДД.ММ.ГГГГ со смещением."""
    try:
        tz = ZoneInfo("Asia/Vladivostok")
    except Exception:
        # Fallback если ZoneInfo не настроен
        tz = datetime.timezone(datetime.timedelta(hours=10))
        
    target_date = datetime.datetime.now(tz) - datetime.timedelta(days=days_offset)
    return target_date.strftime("%d.%m.%Y")

# --- ГЛАВНАЯ ФУНКЦИЯ ДЛЯ ПЛАНИРОВЩИКА ---

async def check_and_process_terminal_report() -> Optional[Dict[str, Any]]:
    """
    Проверяет почту на наличие отчета A-Terminal (Executive summary),
    скачивает его и запускает обработку в БД.
    """
    imap = ImapService()
    filepath = None
    
    # 1. Поиск за СЕГОДНЯ (по Владивостоку)
    today_str = _get_vladivostok_date_str(days_offset=0)
    logger.info(f"[Terminal Check] Ищу 'Executive summary' за {today_str}...")
    
    # Критерии поиска
    criteria_today = AND(from_="aterminal@effex.ru", subject=f"Executive summary {today_str}")
    
    filepath = await asyncio.to_thread(
        imap.download_latest_attachment,
        subject_filter=f"Executive summary {today_str}", # Используем фильтр по теме для download_latest_attachment
        sender_filter="aterminal@effex.ru",
        filename_pattern=r'\.xlsx$'
    )

    # 2. Если не нашли за сегодня, ищем за ВЧЕРА
    if not filepath:
        yesterday_str = _get_vladivostok_date_str(days_offset=1)
        logger.info(f"[Terminal Check] За сегодня нет. Ищу за вчера ({yesterday_str})...")
        
        filepath = await asyncio.to_thread(
            imap.download_latest_attachment,
            subject_filter=f"Executive summary {yesterday_str}",
            sender_filter="aterminal@effex.ru",
            filename_pattern=r'\.xlsx$'
        )

    if not filepath:
        logger.info("[Terminal Check] Актуальный файл терминала не найден.")
        return None

    # 3. Обработка найденного файла
    stats = None
    try:
        logger.info(f"[Terminal Check] Файл найден: {filepath}. Запуск импорта...")
        
        async with SessionLocal() as session:
            # Вызываем функцию обработки (которая уже есть в этом файле ниже)
            await process_terminal_report_file(session, filepath)
            # Примечание: process_terminal_report_file пока не возвращает статистику,
            # но мы можем добавить базовый возврат здесь для логов
            
            stats = {
                "file_name": os.path.basename(filepath),
                "status": "success"
            }
            
        await session.close() # На всякий случай
        
    except Exception as e:
        logger.error(f"❌ [Terminal Check] Ошибка при обработке файла: {e}", exc_info=True)
        stats = {"error": str(e)}
    finally:
        # Удаляем временный файл
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"[Terminal Check] Временный файл удален.")

    return stats

# --- ЛОГИКА ОБРАБОТКИ ФАЙЛА (СУЩЕСТВУЮЩАЯ) ---

async def process_terminal_report_file(session: AsyncSession, file_path: str):
    """
    Главная функция парсинга Excel. Открывает файл и ищет нужные листы (Arrival, Dispatch).
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
        
        await session.commit()
        logger.info("✅ Обработка файла завершена (commit выполнен).")

    except Exception as e:
        await session.rollback()
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
        # В БД нет полей leave_date/leave_time в модели TerminalContainer, 
        # но есть dispatch_date/dispatch_time. Используем их.
        data['dispatch_date'] = parse_date_safe(out_date_val)
        data['dispatch_time'] = parse_time_safe(out_date_val)

        # Поля "ВЫХОДА" (обычно имеют суффикс .1 в Pandas)
        data['out_id'] = clean_string_value(row.get('Id.1')) 
        data['out_transport'] = clean_string_value(row.get('Транспорт.1'))
        data['out_number'] = clean_string_value(row.get('Номер вагона | Номер тягача.1'))
        data['out_driver'] = clean_string_value(row.get('Станция | Водитель.1'))
        
        # Fallback если нет суффикса (редкий случай)
        if not data['out_id'] and 'Id' in row and row.get('Отправлен'):
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
    
    # Разбиваем на пакеты по 1000, чтобы не перегружать
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        await session.execute(stmt, rows[i:i + batch_size])
    
    logger.info(f"💾 Подготовлено к коммиту {len(rows)} записей (Arrival).")

async def _bulk_update_dispatch(session: AsyncSession, rows: List[dict]):
    """SQL для обновления убывших."""
    if not rows:
        return

    # Внимание: используем правильные имена полей модели (dispatch_date вместо leave_date)
    stmt = text("""
        UPDATE terminal_containers
        SET 
            status = :status,
            dispatch_date = :dispatch_date,
            dispatch_time = :dispatch_time,
            out_id = :out_id,
            out_transport = :out_transport,
            out_number = :out_number,
            out_driver = :out_driver,
            updated_at = :updated_at
        WHERE container_number = :container_number
    """)
    
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        await session.execute(stmt, rows[i:i + batch_size])
        
    logger.info(f"🚚 Подготовлено к коммиту {len(rows)} записей (Dispatch).")