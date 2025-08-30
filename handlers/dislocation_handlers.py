# handlers/dislocation_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

from logger import get_logger
from db import SessionLocal
from models import Stats
# ИЗМЕНЕНИЕ: Импортируем обе нужные нам функции из слоя запросов
from queries.containers import get_latest_train_by_container, get_latest_tracking_data

logger = get_logger(__name__)


def _fmt_num(x):
    """Форматирование чисел: убирает .0."""
    try:
        f = float(x)
        if f.is_integer():
            return str(int(f))
        return str(f)
    except (ValueError, TypeError):
        return str(x)


def detect_wagon_type(wagon_number: str) -> str:
    """Определение типа вагона по диапазону."""
    try:
        num = int(str(wagon_number)[:2])
    except (ValueError, TypeError):
        return "платформа"
    if 60 <= num <= 69:
        return "полувагон"
    return "платформа"


COLUMNS = [
    'Номер контейнера', 'Поезд', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной',
    'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции'
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главная рабочая функция поиска контейнеров.
    Теперь она не содержит прямых SQL-запросов.
    """
    if not update.message or not update.message.text or not update.message.from_user:
        logger.warning("[dislocation] получено обновление без необходимой информации")
        if update.message:
            await update.message.reply_text("⛔ Пожалуйста, отправьте текстовый номер контейнера.")
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.username or "—"
    logger.info(f"[dislocation] пользователь {user_id} ({user_name}) отправил сообщение")

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+', user_input.strip()) if c]
    found_rows = []
    not_found = []

    async with SessionLocal() as session:
        for container_number in container_numbers:
            # ИЗМЕНЕНИЕ: Вместо прямого запроса вызываем готовую функцию из queries
            rows = await get_latest_tracking_data(container_number)

            # Логика статистики остается здесь, так как она относится к действию пользователя
            stats_record = Stats(
                container_number=container_number,
                user_id=user_id,
                username=user_name
            )
            session.add(stats_record)
            await session.commit()

            if not rows:
                not_found.append(container_number)
                continue
            
            # rows[0] - это объект Row, который мы и будем использовать
            found_rows.append(rows[0])

    # --- Логика обработки найденных данных ---

    if len(container_numbers) > 1 and found_rows:
        try:
            rows_for_excel = []
            for row in found_rows:
                # Объект Tracking находится внутри Row по индексу [0]
                tracking_obj = row[0]
                train = await get_latest_train_by_container(tracking_obj.container_number) or ""
                rows_for_excel.append([
                    tracking_obj.container_number, train,
                    tracking_obj.from_station, tracking_obj.to_station,
                    tracking_obj.current_station, tracking_obj.operation, tracking_obj.operation_date,
                    tracking_obj.waybill, tracking_obj.km_left, tracking_obj.forecast_days,
                    _fmt_num(tracking_obj.wagon_number), tracking_obj.operation_road,
                ])

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
        # Объект Tracking находится внутри Row по индексу [0]
        tracking_obj = found_rows[0][0]
        
        train = await get_latest_train_by_container(tracking_obj.container_number)
        wagon_number = str(tracking_obj.wagon_number) if tracking_obj.wagon_number else "—"
        wagon_type = detect_wagon_type(wagon_number)

        try:
            km_left_val = float(tracking_obj.km_left)
            forecast_days_calc = round(km_left_val / 600 + 1, 1)
        except (ValueError, TypeError):
            km_left_val = "—"
            forecast_days_calc = "—"

        operation_station = f"{tracking_obj.current_station} 🛤️ ({tracking_obj.operation_road})" if tracking_obj.operation_road else tracking_obj.current_station
        
        header = f"📦 <b>Контейнер</b>: <code>{tracking_obj.container_number}</code>\n"
        if train:
            header += f"🚂 <b>Поезд</b>: <code>{train}</code>\n"
        
        msg = (
            f"{header}\n"
            f"🛤 <b>Маршрут</b>:\n<b>{tracking_obj.from_station}</b> 🚂 → <b>{tracking_obj.to_station}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>:\n{tracking_obj.operation_date} — <i>{tracking_obj.operation}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{_fmt_num(wagon_number)}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{_fmt_num(km_left_val)}</b> км\n\n"
            f"⏳ <b>Оценка времени в пути</b>:\n~<b>{_fmt_num(forecast_days_calc)}</b> суток"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text("Ничего не найдено по введённым номерам.")

