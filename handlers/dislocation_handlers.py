# handlers/dislocation_handlers.py
import asyncio
import os
from telegram import Update
from telegram.ext import ContextTypes
import re
from typing import Optional

from logger import get_logger
from db import SessionLocal
from models import UserRequest, Tracking
from queries.user_queries import add_user_request, register_user_if_not_exists
from queries.notification_queries import get_tracking_data_for_containers
from services.railway_router import get_remaining_distance_on_route
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.railway_utils import get_railway_abbreviation
import config

logger = get_logger(__name__)

# --- НОВАЯ ЛОГИКА: ОПРЕДЕЛЕНИЕ ТИПА ВАГОНА ---

def get_wagon_type_by_number(wagon_number: Optional[str | int]) -> str:
    """
    Определяет тип вагона по первой цифре номера, согласно предоставленной логике.
    """
    if wagon_number is None:
        return 'н/д'
    
    wagon_str = str(wagon_number).removesuffix('.0').strip()
    
    if not wagon_str or not wagon_str[0].isdigit():
        return 'Прочий' 
    
    first_digit = wagon_str[0]
    
    if first_digit == '6':
        return 'Полувагон'
    elif first_digit == '9' or first_digit == '5':
        return 'Платформа'
    else:
        return 'Прочий'

# --- Основной обработчик сообщений ---

def normalize_text_input(text: str) -> list[str]:
    """Извлекает и нормализует номера контейнеров или другие запросы из текста."""
    text = text.upper().strip()
    items = re.split(r'[,\s;\n]+', text)
    normalized_items = sorted(list(set(filter(None, items))))
    return normalized_items

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает текстовые сообщения: ищет контейнеры, логирует запрос, отправляет результат.
    """
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        logger.warning("Получено сообщение без текста или пользователя.")
        return

    await register_user_if_not_exists(user)

    search_terms = normalize_text_input(message.text)
    if not search_terms:
        await message.reply_text("Пожалуйста, введите номер контейнера или другой запрос.")
        return

    query_text_log = ", ".join(search_terms)
    logger.info(f"[dislocation] пользователь {user.id} ({user.username}) отправил текст для поиска: {query_text_log}")

    # Логируем запрос пользователя в базу данных
    try:
        await add_user_request(telegram_id=user.id, query_text=query_text_log)
    except Exception as log_err:
        logger.error(f"Не удалось залогировать запрос пользователя {user.id}: {log_err}", exc_info=True)

    tracking_results = await get_tracking_data_for_containers(search_terms)

    if not tracking_results:
        await message.reply_text(f"Ничего не найдено по номерам: {query_text_log}")
        return

    # --- Формирование ответа (ОДИНОЧНЫЙ КОНТЕЙНЕР) ---
    if len(tracking_results) == 1:
        result = tracking_results[0]
        
        # --- ЛОГИКА ОПРЕДЕЛЕНИЯ ИСТОЧНИКА ДАННЫХ (ПРИОРИТЕТ: РАСЧЕТ) ---
        remaining_distance = await get_remaining_distance_on_route(
            start_station=result.from_station,
            end_station=result.to_station,
            current_station=result.current_station
        )
        
        km_left_display = None
        forecast_days_display = 0.0
        source_log_tag = "Н/Д"
        distance_label = "Осталось км (БД):" 

        if remaining_distance is not None:
            source_log_tag = "РАСЧЕТ"
            km_left_display = remaining_distance
            forecast_days_display = round(remaining_distance / 600 + 1, 1) if remaining_distance > 0 else 0.0
            distance_label = "Тарифное расстояние:"
        else:
            source_log_tag = "БД (Fallback)"
            km_left_display = result.km_left
            forecast_days_display = result.forecast_days or 0.0
            distance_label = "Осталось км (БД):"
            
        logger.info(f"[dislocation] Контейнер {result.container_number}: Расстояние ({km_left_display} км) взято из источника: {source_log_tag}")
        # --- КОНЕЦ ЛОГИКИ ОПРЕДЕЛЕНИЯ ИСТОЧНИКА ДАННЫХ ---
        
        wagon_number_raw = result.wagon_number
        wagon_number_cleaned = str(wagon_number_raw).removesuffix('.0') if wagon_number_raw else 'н/д'
        
        wagon_type_display = get_wagon_type_by_number(wagon_number_raw)
        
        railway_abbreviation = get_railway_abbreviation(result.operation_road)

        # ФОРМАТИРОВАНИЕ СООБЩЕНИЯ С ЭМОДЗИ
        response_text = (
            f"📦 **Статус контейнера: {result.container_number}**\n"
            f"═════════════════════\n"
            f"📍 *Маршрут:*\n"
            f"Отпр: `{result.from_station}`\n"
            f"Назн: `{result.to_station}`\n"
            f"═════════════════════\n"
            f"🚂 *Текущая дислокация:*\n"
            f"**Станция:** {result.current_station} (Дорога: `{railway_abbreviation}`)\n"
            f"**Операция:** `{result.operation}`\n"
            f"**Дата/Время:** `{result.operation_date}`\n"
            f"**Вагон:** `{wagon_number_cleaned}` (Тип: `{wagon_type_display}`)\n"
            f"**Накладная:** `{result.waybill}`\n"
            f"═════════════════════\n"
            f"🛣️ *Прогноз:*\n"
            f"**{distance_label}** **{km_left_display or 'н/д'} км**\n" 
            f"**Прогноз (дни):** `{forecast_days_display:.1f} дн.`"
        )
        await message.reply_markdown(response_text)

    else:
        # Логика для нескольких результатов (Excel)
        final_report_data = []
        
        excel_columns = list(config.TRACKING_REPORT_COLUMNS)
        
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ EXCEL: Изменяем заголовки, чтобы соответствовать 13 элементам данных.
        try:
             km_left_index = excel_columns.index('Расстояние оставшееся')
             wagon_index = excel_columns.index('Вагон')
             
             # 1. Вставляем "Источник данных"
             excel_columns.insert(km_left_index + 1, 'Источник данных')

             # 2. Удаляем старый заголовок "Вагон"
             excel_columns.pop(wagon_index)
             
             # 3. Вставляем "Вагон" и "Тип вагона"
             excel_columns.insert(wagon_index, 'Вагон')
             excel_columns.insert(wagon_index + 1, 'Тип вагона')
             
             # 4. Удаляем "Прогноз прибытия (дни)"
             excel_columns.pop(excel_columns.index('Прогноз прибытия (дни)'))
             
             # 5. Добавляем "Прогноз прибытия (дни)" в конец (чтобы сохранить 13 элементов)
             excel_columns.append('Прогноз прибытия (дни)')


        except ValueError:
             # На случай, если какая-то колонка отсутствует, добавляем в конец
             excel_columns.append('Источник данных') 
             excel_columns.append('Тип вагона') 


        for db_row in tracking_results:
            
            recalculated_distance = await get_remaining_distance_on_route(
                start_station=db_row.from_station,
                end_station=db_row.to_station,
                current_station=db_row.current_station
            )
            
            km_left = None
            forecast_days = 0.0
            source_tag = ""
            
            if recalculated_distance is not None:
                source_tag = "Тариф (10-01)"
                km_left = recalculated_distance
                forecast_days = round(recalculated_distance / 600 + 1, 1) if recalculated_distance > 0 else 0.0
            else:
                source_tag = "БД"
                km_left = db_row.km_left
                forecast_days = db_row.forecast_days or 0.0

            logger.info(f"[dislocation] Контейнер {db_row.container_number}: Расстояние ({km_left} км) взято из источника: {source_tag}")
             
            wagon_number_raw = db_row.wagon_number
            wagon_number_cleaned = str(wagon_number_raw).removesuffix('.0') if wagon_number_raw else None
            
            wagon_type_for_excel = get_wagon_type_by_number(wagon_number_raw)

            railway_display_name = db_row.operation_road 


            # Формирование строки для Excel. (13 элементов)
            excel_row = [
                 db_row.container_number, db_row.from_station, db_row.to_station,
                 db_row.current_station, db_row.operation, db_row.operation_date,
                 db_row.waybill, km_left, source_tag, 
                 wagon_number_cleaned, wagon_type_for_excel, railway_display_name,
                 forecast_days, # Прогноз в конце
             ]
            final_report_data.append(excel_row)

        file_path = None
        try:
             file_path = await asyncio.to_thread(
                 create_excel_file,
                 final_report_data,
                 excel_columns # Используем измененный список колонок (13 элементов)
             )
             filename = get_vladivostok_filename(prefix="Дислокация")

             with open(file_path, "rb") as f:
                 await message.reply_document(
                     document=f,
                     filename=filename,
                     caption=f"Найдены данные по {len(final_report_data)} контейнерам."
                 )
             logger.info(f"Отправлен Excel отчет по запросу пользователя {user.id}")
        except Exception as send_err:
             logger.error(f"Ошибка отправки Excel отчета пользователю {user.id}: {send_err}", exc_info=True)
             await message.reply_text("Не удалось отправить Excel файл.")
        finally:
             if file_path and os.path.exists(file_path):
                 try:
                     os.remove(file_path)
                 except OSError as e:
                      logger.error(f"Не удалось удалить временный файл {file_path}: {e}")