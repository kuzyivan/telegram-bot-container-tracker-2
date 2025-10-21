# handlers/dislocation_handlers.py
import asyncio
import os
from telegram import Update
from telegram.ext import ContextTypes
import re

from logger import get_logger
from db import SessionLocal
from models import UserRequest, Tracking
# ✅ Финальное исправление импорта и вызова на log_user_request
from queries.user_queries import log_user_request, register_user_if_not_exists
from queries.notification_queries import get_tracking_data_for_containers
from services.railway_router import get_remaining_distance_on_route
from utils.send_tracking import create_excel_file, get_vladivostok_filename
import config

logger = get_logger(__name__)

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
        # ✅ Финальное исправление вызова функции
        await log_user_request(telegram_id=user.id, query_text=query_text_log)
    except Exception as log_err:
        logger.error(f"Не удалось залогировать запрос пользователя {user.id}: {log_err}", exc_info=True)

    tracking_results = await get_tracking_data_for_containers(search_terms)

    if not tracking_results:
        await message.reply_text(f"Ничего не найдено по номерам: {query_text_log}")
        return

    # --- Формирование ответа ---
    if len(tracking_results) == 1:
        result = tracking_results[0]
        remaining_distance = await get_remaining_distance_on_route(
            start_station=result.from_station,
            end_station=result.to_station,
            current_station=result.current_station
        )
        km_left_display = remaining_distance if remaining_distance is not None else result.km_left
        forecast_days_display = round(remaining_distance / 600 + 1, 1) if remaining_distance is not None and remaining_distance > 0 else (result.forecast_days or 0.0)

        response_text = (
            f"**Контейнер:** {result.container_number}\n"
            f"**Отпр:** {result.from_station}\n"
            f"**Назн:** {result.to_station}\n"
            f"**Текущая:** {result.current_station}\n"
            f"**Операция:** {result.operation}\n"
            f"**Дата/Время:** {result.operation_date}\n"
            f"**Осталось км:** {km_left_display or 'н/д'}\n"
            f"**Прогноз (дни):** {forecast_days_display:.1f}\n"
            f"**Накладная:** {result.waybill}\n"
            f"**Вагон:** {result.wagon_number}\n"
            f"**Дорога:** {result.operation_road}"
        )
        await message.reply_markdown(response_text)

    else:
        final_report_data = []
        for db_row in tracking_results:
             recalculated_distance = await get_remaining_distance_on_route(
                 start_station=db_row.from_station,
                 end_station=db_row.to_station,
                 current_station=db_row.current_station
             )
             km_left = recalculated_distance if recalculated_distance is not None else db_row.km_left
             forecast_days = round(recalculated_distance / 600 + 1, 1) if recalculated_distance is not None and recalculated_distance > 0 else (db_row.forecast_days or 0.0)

             excel_row = [
                 db_row.container_number, db_row.from_station, db_row.to_station,
                 db_row.current_station, db_row.operation, db_row.operation_date,
                 db_row.waybill, km_left, forecast_days,
                 db_row.wagon_number, db_row.operation_road,
             ]
             final_report_data.append(excel_row)

        file_path = None
        try:
             file_path = await asyncio.to_thread(
                 create_excel_file,
                 final_report_data,
                 config.TRACKING_REPORT_COLUMNS
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