# handlers/dislocation_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlalchemy import select
import re

from logger import get_logger
from db import SessionLocal
from models import Tracking, Stats

# ИСПРАВЛЕНИЕ 1: Убираем try...except и оставляем один правильный, прямой импорт
from queries.containers import get_latest_train_by_container

logger = get_logger(__name__)


def _fmt_num(x):
    """Форматирование чисел: убирает .0 даже если вход — строка."""
    try:
        f = float(x)
        if f.is_integer():
            return str(int(f))
        return str(f)
    except Exception:
        return str(x)


def detect_wagon_type(wagon_number: str) -> str:
    """Определение типа вагона по диапазону: 60–69 → полувагон, остальное → платформа."""
    try:
        num = int(wagon_number[:2])
    except Exception:
        return "платформа"
    if 60 <= num <= 69:
        return "полувагон"
    return "платформа"


COLUMNS = [
    'Номер контейнера', 'Поезд',
    'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главная рабочая функция поиска контейнеров.
    """
    # ИСПРАВЛЕНИЕ 2: Добавляем полную проверку на наличие message, text и from_user
    if not update.message or not update.message.text or not update.message.from_user:
        logger.warning(f"[dislocation] получено обновление без необходимой информации (сообщение/текст/пользователь)")
        # Если ответить не можем, просто выходим
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
            result = await session.execute(
                select(Tracking).where(
                    Tracking.container_number == container_number
                ).order_by(
                    Tracking.operation_date.desc()
                )
            )
            rows = result.fetchall()

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

            # Берем первую (самую свежую) строку
            found_rows.append(rows[0])

    if len(container_numbers) > 1 and found_rows:
        try:
            rows_for_excel = []
            for row in found_rows:
                train = await get_latest_train_by_container(row.container_number) or ""
                rows_for_excel.append([
                    row.container_number, train,
                    row.from_station, row.to_station,
                    row.current_station, row.operation, row.operation_date,
                    row.waybill, row.km_left, row.forecast_days,
                    _fmt_num(row.wagon_number), row.operation_road,
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
        row = found_rows[0]
        train = await get_latest_train_by_container(row.container_number)
        wagon_number = str(row.wagon_number) if row.wagon_number else "—"
        wagon_type = detect_wagon_type(wagon_number)

        try:
            km_left_val = float(row.km_left)
            forecast_days_calc = round(km_left_val / 600 + 1, 1)
        except (ValueError, TypeError):
            km_left_val = "—"
            forecast_days_calc = "—"

        operation_station = f"{row.current_station} 🛤️ ({row.operation_road})" if row.operation_road else row.current_station
        
        header = f"📦 <b>Контейнер</b>: <code>{row.container_number}</code>\n"
        if train:
            header += f"🚂 <b>Поезд</b>: <code>{train}</code>\n"
        
        msg = (
            f"{header}\n"
            f"🛤 <b>Маршрут</b>:\n<b>{row.from_station}</b> 🚂 → <b>{row.to_station}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>:\n{row.operation_date} — <i>{row.operation}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{_fmt_num(wagon_number)}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{_fmt_num(km_left_val)}</b> км\n\n"
            f"⏳ <b>Оценка времени в пути</b>:\n~<b>{_fmt_num(forecast_days_calc)}</b> суток"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text("Ничего не найдено по введённым номерам.")