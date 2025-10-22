# handlers/dislocation_handlers.py
import asyncio
import os
from telegram import Update
from telegram.ext import ContextTypes
import re
from typing import Optional
from sqlalchemy import select

from logger import get_logger
from db import SessionLocal
# ✅ ИСПРАВЛЕННЫЙ ИМПОРТ: Указываем правильный путь к TerminalContainer
from models import UserRequest, Tracking
from model.terminal_container import TerminalContainer # <<< ИСПРАВЛЕНО ЗДЕСЬ
from queries.user_queries import add_user_request, register_user_if_not_exists
from queries.notification_queries import get_tracking_data_for_containers
from services.railway_router import get_remaining_distance_on_route
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.railway_utils import get_railway_abbreviation
import config
from utils.keyboards import create_single_container_excel_keyboard

logger = get_logger(__name__)

# --- Логика определения типа вагона ---

def get_wagon_type_by_number(wagon_number: Optional[str | int]) -> str:
    # ... (код остается прежним) ...
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

def normalize_text_input(text: str) -> list[str]:
    # ... (код остается прежним) ...
    text = text.upper().strip()
    items = re.split(r'[,\s;\n]+', text)
    normalized_items = sorted(list(set(filter(None, items))))
    return normalized_items

# --- Асинхронная функция для получения поезда ---
async def get_train_for_container(container_number: str) -> str | None:
    """Получает номер поезда из terminal_containers."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(TerminalContainer.train)
            .where(TerminalContainer.container_number == container_number)
            .limit(1)
        )
        train = result.scalar_one_or_none()
        return train

# --- Основной обработчик сообщений ---

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

    # Логируем запрос пользователя
    try:
        await add_user_request(telegram_id=user.id, query_text=query_text_log)
    except Exception as log_err:
        logger.error(f"Не удалось залогировать запрос пользователя {user.id}: {log_err}", exc_info=True)

    tracking_results = await get_tracking_data_for_containers(search_terms)

    if not tracking_results:
        await message.reply_text(f"Ничего не найдено по номерам: {query_text_log}")
        return

    # --- Логика: ОДИН КОНТЕЙНЕР ---
    if len(tracking_results) == 1:
        result = tracking_results[0]

        # --- Получаем номер поезда ---
        train_number = await get_train_for_container(result.container_number)
        train_display = f"Поезд: `{train_number}`\n" if train_number else ""

        # --- Расчет расстояния ---
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

        wagon_number_raw = result.wagon_number
        wagon_number_cleaned = str(wagon_number_raw).removesuffix('.0') if wagon_number_raw else 'н/д'
        wagon_type_display = get_wagon_type_by_number(wagon_number_raw)
        railway_abbreviation = get_railway_abbreviation(result.operation_road)

        # --- Форматирование ответа ---
        response_text = (
            f"📦 **Статус контейнера: {result.container_number}**\n"
            f"═════════════════════\n"
            f"📍 *Маршрут:*\n"
            f"{train_display}" # Строка с поездом
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

        await message.reply_markdown(
            response_text,
            reply_markup=create_single_container_excel_keyboard(result.container_number)
        )

    # --- Логика: МНОГО КОНТЕЙНЕРОВ (Ответ Excel) ---
    else:
        # ... (логика формирования Excel остается прежней) ...
        final_report_data = []
        EXCEL_HEADERS = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Вагон',
            'Тип вагона', 'Дорога операции'
        ]
        excel_columns = EXCEL_HEADERS
        for db_row in tracking_results:
            recalculated_distance = await get_remaining_distance_on_route(
                start_station=db_row.from_station,
                end_station=db_row.to_station,
                current_station=db_row.current_station
            )
            km_left = recalculated_distance if recalculated_distance is not None else db_row.km_left
            source_tag = "РАСЧЕТ" if recalculated_distance is not None else "БД"
            logger.info(f"[dislocation] Контейнер {db_row.container_number}: Расстояние ({km_left} км) взято из источника: {source_tag}")
            wagon_number_raw = db_row.wagon_number
            wagon_number_cleaned = str(wagon_number_raw).removesuffix('.0') if wagon_number_raw else None
            wagon_type_for_excel = get_wagon_type_by_number(wagon_number_raw)
            railway_display_name = db_row.operation_road
            excel_row = [
                 db_row.container_number, db_row.from_station, db_row.to_station,
                 db_row.current_station, db_row.operation, db_row.operation_date,
                 db_row.waybill, km_left,
                 wagon_number_cleaned, wagon_type_for_excel, railway_display_name,
             ]
            final_report_data.append(excel_row)

        file_path = None
        try:
             file_path = await asyncio.to_thread(
                 create_excel_file,
                 final_report_data,
                 excel_columns
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

# --- Обработчик кнопки скачивания Excel для одного контейнера ---

async def handle_single_container_excel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код остается прежним) ...
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("get_excel_single_") or not update.effective_user:
        return
    await query.answer("⏳ Готовлю Excel-отчет...")
    container_number = query.data.split("_")[-1]
    user = update.effective_user
    logger.info(f"[dislocation] Пользователь {user.id} запросил Excel для {container_number} через кнопку.")
    tracking_results = await get_tracking_data_for_containers([container_number])
    if not tracking_results:
        if query.message and query.message.text:
            await query.edit_message_text("❌ Ошибка: Не удалось найти актуальные данные для Excel.")
        elif query.message:
             await context.bot.send_message(user.id, "❌ Ошибка: Не удалось найти актуальные данные для Excel.")
        return

    db_row = tracking_results[0]
    recalculated_distance = await get_remaining_distance_on_route(
        start_station=db_row.from_station,
        end_station=db_row.to_station,
        current_station=db_row.current_station
    )
    km_left = recalculated_distance if recalculated_distance is not None else db_row.km_left
    wagon_number_raw = db_row.wagon_number
    wagon_number_cleaned = str(wagon_number_raw).removesuffix('.0') if wagon_number_raw else None
    wagon_type_for_excel = get_wagon_type_by_number(wagon_number_raw)
    railway_display_name = db_row.operation_road
    EXCEL_HEADERS = [
        'Номер контейнера', 'Станция отправления', 'Станция назначения',
        'Станция операции', 'Операция', 'Дата и время операции',
        'Номер накладной', 'Расстояние оставшееся', 'Вагон',
        'Тип вагона', 'Дорога операции'
    ]
    final_report_data = [[
         db_row.container_number, db_row.from_station, db_row.to_station,
         db_row.current_station, db_row.operation, db_row.operation_date,
         db_row.waybill, km_left,
         wagon_number_cleaned, wagon_type_for_excel, railway_display_name,
     ]]
    file_path = None
    try:
         file_path = await asyncio.to_thread(
             create_excel_file,
             final_report_data,
             EXCEL_HEADERS
         )
         filename = get_vladivostok_filename(prefix=container_number)
         with open(file_path, "rb") as f:
              await context.bot.send_document(
                 chat_id=user.id,
                 document=f,
                 filename=filename,
                 caption=f"✅ Отчет по контейнеру {container_number}."
             )
         logger.info(f"Отправлен Excel отчет для {container_number} пользователю {user.id}")
         if query.message and query.message.text:
             await query.edit_message_reply_markup(reply_markup=None)

    except Exception as send_err:
         logger.error(f"Ошибка отправки Excel отчета пользователю {user.id}: {send_err}", exc_info=True)
         await context.bot.send_message(user.id, "❌ Не удалось отправить Excel файл.")
    finally:
         if file_path and os.path.exists(file_path):
             try:
                 os.remove(file_path)
             except OSError as e:
                  logger.error(f"Не удалось удалить временный файл {file_path}: {e}")