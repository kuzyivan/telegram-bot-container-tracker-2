# handlers/dislocation_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re
from typing import List

from logger import get_logger
from db import SessionLocal
from models import Stats, Tracking
from queries.containers import get_latest_train_by_container, get_latest_tracking_data, get_tracking_data_by_wagons
from services.railway_router import get_remaining_distance_on_route

logger = get_logger(__name__)

def _fmt_num(x):
    try:
        f = float(x)
        if f.is_integer(): return str(int(f))
        return str(f)
    except (ValueError, TypeError): return str(x)

def detect_wagon_type(wagon_number: str) -> str:
    try:
        num = int(str(wagon_number)[:2])
    except (ValueError, TypeError): return "платформа"
    if 60 <= num <= 69: return "полувагон"
    return "платформа"

def _are_all_tokens_wagons(tokens: List[str]) -> bool:
    """Проверяет, являются ли все токены 8-значными числами."""
    if not tokens:
        return False
    return all(t.isdigit() and len(t) == 8 for t in tokens)

COLUMNS = [
    'Номер контейнера', 'Поезд', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной',
    'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции'
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.message.from_user:
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.username or "—"
    text = update.message.text.strip()
    
    logger.info(f"[dislocation] пользователь {user_id} ({user_name}) отправил текст для поиска: {text}")
    
    input_tokens = [c.strip().upper() for c in re.split(r'[\s,\n.]+', text) if c]
    
    if not input_tokens:
        await update.message.reply_text("Пожалуйста, введите корректный номер контейнера или вагона.")
        return

    if _are_all_tokens_wagons(input_tokens):
        wagon_numbers = input_tokens
        logger.info(f"Распознан поиск по номеру вагона(ов): {', '.join(wagon_numbers)}")
        
        tracking_results = await get_tracking_data_by_wagons(wagon_numbers)
        
        if not tracking_results:
            await update.message.reply_text(f"Не найдено активных контейнеров на вагонах: `{', '.join(wagon_numbers)}`.", parse_mode=ParseMode.MARKDOWN)
            return
            
        if len(wagon_numbers) > 1:
            rows_for_excel = []
            for tracking_obj in tracking_results:
                train = await get_latest_train_by_container(tracking_obj.container_number) or ""
                remaining_distance = await get_remaining_distance_on_route(
                    start_station=tracking_obj.from_station,
                    end_station=tracking_obj.to_station,
                    current_station=tracking_obj.current_station
                )
                km_left = remaining_distance if remaining_distance is not None else tracking_obj.km_left
                forecast_days = round(float(km_left or 0) / 600 + 1, 1) if km_left and float(km_left or 0) > 0 else 0.0
                
                rows_for_excel.append([
                    tracking_obj.container_number, train,
                    tracking_obj.from_station, tracking_obj.to_station,
                    tracking_obj.current_station, tracking_obj.operation, tracking_obj.operation_date,
                    tracking_obj.waybill, km_left, forecast_days,
                    _fmt_num(tracking_obj.wagon_number), tracking_obj.operation_road,
                ])
            
            from utils.send_tracking import create_excel_file, get_vladivostok_filename
            
            filename_prefix = f"Вагоны_{'-'.join(wagon_numbers[:3])}"
            caption = f"На вагонах `{', '.join(wagon_numbers)}` найдено контейнеров: {len(rows_for_excel)} шт."

            file_path = create_excel_file(rows_for_excel, COLUMNS)
            filename = get_vladivostok_filename(filename_prefix)

            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename, caption=caption, parse_mode=ParseMode.MARKDOWN)
            return
        else:
            wagon_number = wagon_numbers[0]
            first_container = tracking_results[0]
            train = await get_latest_train_by_container(first_container.container_number) or "неизвестен"

            header_lines = [
                f"🚆 *Вагон*: `{wagon_number}` ({detect_wagon_type(wagon_number)})",
                f"📍 *Текущая станция*: `{first_container.current_station}` 🛤️ ({first_container.operation_road})",
                f"📅 *Последняя операция*: {first_container.operation_date} — _{first_container.operation}_",
            ]
            if train != "неизвестен":
                header_lines.append(f"🚂 *Поезд*: `{train}`")
            
            message = "\n".join(header_lines)
            message += f"\n\nНа вагоне найдено контейнеров: *{len(tracking_results)}* шт."
            message += "\n" + ("-"*20)

            for tracking_obj in tracking_results:
                remaining_distance = await get_remaining_distance_on_route(
                    start_station=tracking_obj.from_station,
                    end_station=tracking_obj.to_station,
                    current_station=tracking_obj.current_station
                )
                km_left = remaining_distance if remaining_distance is not None else tracking_obj.km_left
                forecast_days = round(float(km_left or 0) / 600 + 1, 1) if km_left and float(km_left or 0) > 0 else 0.0
                
                container_part = (
                    f"\n\n📦 *Контейнер*: `{tracking_obj.container_number}`\n"
                    f"🛤 *Маршрут*: `{tracking_obj.from_station}` → `{tracking_obj.to_station}`\n"
                    f"📏 *Осталось ехать*: {_fmt_num(km_left)} км (~{_fmt_num(forecast_days)} суток)"
                )
                message += container_part
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            return

    else:
        container_numbers = input_tokens
        found_rows = []
        not_found = []

        async with SessionLocal() as session:
            for container_number in container_numbers:
                rows = await get_latest_tracking_data(container_number)
                stats_record = Stats(container_number=container_number, user_id=user_id, username=user_name)
                session.add(stats_record)
                await session.commit()
                if not rows:
                    not_found.append(container_number)
                    continue
                found_rows.append(rows[0])

        if len(container_numbers) > 1 and found_rows:
            try:
                rows_for_excel = []
                # <<< НАЧАЛО ИСПРАВЛЕНИЙ ВО ВТОРОМ БЛОКЕ >>>
                for tracking_obj in found_rows:
                    # Используем доступ к атрибутам через точку
                    train = await get_latest_train_by_container(tracking_obj.container_number) or ""
                    remaining_distance = await get_remaining_distance_on_route(
                        start_station=tracking_obj.from_station,
                        end_station=tracking_obj.to_station,
                        current_station=tracking_obj.current_station
                    )
                    km_left = remaining_distance if remaining_distance is not None else tracking_obj.km_left
                    # Приводим km_left к float для безопасности
                    forecast_days = round(float(km_left or 0) / 600 + 1, 1) if km_left and float(km_left or 0) > 0 else 0.0
                    rows_for_excel.append([
                        tracking_obj.container_number, train,
                        tracking_obj.from_station, tracking_obj.to_station,
                        tracking_obj.current_station, tracking_obj.operation, tracking_obj.operation_date,
                        tracking_obj.waybill, km_left, forecast_days,
                        _fmt_num(tracking_obj.wagon_number), tracking_obj.operation_road,
                    ])
                # <<< КОНЕЦ ИСПРАВЛЕНИЙ >>>

                from utils.send_tracking import create_excel_file, get_vladivostok_filename
                file_path = create_excel_file(rows_for_excel, COLUMNS)
                filename = get_vladivostok_filename()
                with open(file_path, "rb") as f:
                    await update.message.reply_document(document=f, filename=filename)
            except Exception as e:
                logger.error(f"Ошибка отправки Excel пользователю {user_id}: {e}", exc_info=True)

            if not_found:
                await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
            return

        if found_rows:
            tracking_obj = found_rows[0]
            train = await get_latest_train_by_container(tracking_obj.container_number)
            wagon_number_str = str(tracking_obj.wagon_number) if tracking_obj.wagon_number else "—"
            wagon_type = detect_wagon_type(wagon_number_str)
            
            km_left_val = tracking_obj.km_left
            distance_str = f"📏 *Осталось ехать (по данным ЭТРАН)*: *{_fmt_num(km_left_val)}* км\n"

            remaining_distance = await get_remaining_distance_on_route(
                start_station=tracking_obj.from_station,
                end_station=tracking_obj.to_station,
                current_station=tracking_obj.current_station
            )
            
            if remaining_distance is not None:
                distance_str = f"🚆 *Осталось ехать (расчет по OSM)*: *{_fmt_num(remaining_distance)}* км\n"
                km_left_val = remaining_distance

            try:
                km_float = float(km_left_val) if km_left_val is not None else 0.0
                forecast_days_calc = round(km_float / 600 + 1, 1) if km_float > 0 else 0
            except (ValueError, TypeError):
                forecast_days_calc = "—"

            operation_station = f"`{tracking_obj.current_station}` 🛤️ ({tracking_obj.operation_road})" if tracking_obj.operation_road else f"`{tracking_obj.current_station}`"
            header = f"📦 *Контейнер*: `{tracking_obj.container_number}`\n"
            if train:
                header += f"🚂 *Поезд*: `{train}`\n"
            msg = (
                f"{header}\n"
                f"🛤 *Маршрут*:\n`{tracking_obj.from_station}` 🚂 → `{tracking_obj.to_station}`\n\n"
                f"📍 *Текущая станция*: {operation_station}\n"
                f"📅 *Последняя операция*:\n{tracking_obj.operation_date} — _{tracking_obj.operation}_\n\n"
                f"🚆 *Вагон*: `{_fmt_num(wagon_number_str)}` ({wagon_type})\n"
                f"{distance_str}\n"
                f"⏳ *Оценка времени в пути*:\n~*{_fmt_num(forecast_days_calc)}* суток"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            return

        if not_found:
            await update.message.reply_text(f"Ничего не найдено по номерам: {', '.join(not_found)}")