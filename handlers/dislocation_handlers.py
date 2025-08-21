# handlers/dislocation_handlers.py
from __future__ import annotations

import re
from typing import List, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from sqlalchemy import select

from logger import get_logger
from db import SessionLocal
from models import Tracking, Stats
from utils.send_tracking import create_excel_file, get_vladivostok_filename

logger = get_logger(__name__)

# Колонки для Excel
COLUMNS = [
    "Номер контейнера", "Станция отправления", "Станция назначения",
    "Станция операции", "Операция", "Дата и время операции",
    "Номер накладной", "Расстояние оставшееся", "Прогноз прибытия (дней)",
    "Номер вагона", "Дорога операции"
]


def _parse_container_input(text: str) -> List[str]:
    """
    Разбирает ввод пользователя: допускает разделители пробел/запятая/точка/перенос строки.
    Возвращает список нормализованных номеров (UPPER, без пустых).
    """
    return [c.strip().upper() for c in re.split(r"[\s,\n\.]+", text.strip()) if c.strip()]


def _format_single_message(row: List) -> str:
    """
    Формирует HTML-сообщение о дислокации для одного контейнера.
    row соответствует порядку колонок COLUMNS.
    """
    container = row[0]
    from_station = row[1]
    to_station = row[2]
    current_station = row[3]
    operation = row[4]
    operation_dt = row[5]
    waybill = row[6]
    km_left = row[7]
    forecast_days = row[8]
    wagon_number = row[9]
    op_road = row[10]

    wagon_str = str(wagon_number) if wagon_number else "—"
    wagon_type = "полувагон" if wagon_str.startswith("6") else "платформа"

    try:
        km_val = float(km_left)
        forecast_calc = round(km_val / 600 + 1, 1)
        km_show = f"{km_val:.0f}"
    except Exception:
        km_show = "—"
        forecast_calc = "—"

    station_show = f"{current_station} 🛤️ ({op_road})" if op_road else f"{current_station}"

    msg = (
        f"📦 <b>Контейнер</b>: <code>{container}</code>\n\n"
        f"🛤 <b>Маршрут</b>:\n"
        f"<b>{from_station}</b> 🚂 → <b>{to_station}</b>\n\n"
        f"📍 <b>Текущая станция</b>: {station_show}\n"
        f"📅 <b>Последняя операция</b>:\n"
        f"{operation_dt} — <i>{operation}</i>\n\n"
        f"🚆 <b>Вагон</b>: <code>{wagon_str}</code> ({wagon_type})\n"
        f"📏 <b>Осталось ехать</b>: <b>{km_show}</b> км\n\n"
        f"⏳ <b>Оценка времени в пути</b>:\n"
        f"~<b>{forecast_calc}</b> суток (расчет: {km_show} км / 600 км/сутки + 1 день)"
    )
    if waybill:
        msg += f"\n\n🧾 <b>Накладная</b>: <code>{waybill}</code>"

    return msg


async def _fetch_latest_rows_for_containers(
    session: SessionLocal,
    containers: List[str],
) -> Tuple[List[List], List[str]]:
    """
    Для каждого контейнера возвращает последнюю запись (по дате операции).
    Возвращает: (список строк для найденных, список не найденных номеров)
    """
    found_rows: List[List] = []
    not_found: List[str] = []

    for container in containers:
        result = await session.execute(
            select(
                Tracking.container_number,
                Tracking.from_station,
                Tracking.to_station,
                Tracking.current_station,
                Tracking.operation,
                Tracking.operation_date,
                Tracking.waybill,
                Tracking.km_left,
                Tracking.forecast_days,
                Tracking.wagon_number,
                Tracking.operation_road,
            )
            .where(Tracking.container_number == container)
            .order_by(Tracking.operation_date.desc())
        )
        rows = result.fetchall()

        # Лог и запись в Stats
        session.add(
            Stats(
                container_number=container,
                user_id=None,   # заполним выше при наличии update.message
                username=None,  # заполним выше при наличии update.message
            )
        )

        if not rows:
            not_found.append(container)
            logger.info(f"Контейнер не найден: {container}")
            continue

        row = rows[0]
        found_rows.append(list(row))
        logger.info(f"Контейнер найден: {container}")

    await session.commit()
    return found_rows, not_found


async def handle_dislocation_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный обработчик текстового сообщения с номерами контейнеров.
    Его надо привязать к MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dislocation_message)
    если вы хотите, чтобы ВСЕ обычные тексты считались запросом дислокации.
    Либо дергать из нужных мест вручную.
    """
    user = update.effective_user
    user_id = user.id if user else "—"
    user_name = user.username if user else "—"
    logger.info(f"handle_dislocation_message: пользователь {user_id} ({user_name}) отправил сообщение")

    if not update.message or not update.message.text:
        logger.warning(f"Пустой ввод от пользователя {user_id}")
        await update.message.reply_text("⛔ Пожалуйста, отправьте текстовый номер контейнера.")
        return

    # Разбор входа
    user_input = update.message.text
    logger.info(f"Обрабатываем ввод: {user_input}")
    containers = _parse_container_input(user_input)

    if not containers:
        await update.message.reply_text("Не вижу номеров контейнеров. Введите, например: MSCU1234567")
        return

    # Поиск в БД
    async with SessionLocal() as session:
        # обновим user_id/username в Stats перед коммитом
        found_rows: List[List] = []
        not_found: List[str] = []

        for container in containers:
            result = await session.execute(
                select(
                    Tracking.container_number,
                    Tracking.from_station,
                    Tracking.to_station,
                    Tracking.current_station,
                    Tracking.operation,
                    Tracking.operation_date,
                    Tracking.waybill,
                    Tracking.km_left,
                    Tracking.forecast_days,
                    Tracking.wagon_number,
                    Tracking.operation_road,
                )
                .where(Tracking.container_number == container)
                .order_by(Tracking.operation_date.desc())
            )
            rows = result.fetchall()

            session.add(
                Stats(
                    container_number=container,
                    user_id=update.message.from_user.id,
                    username=update.message.from_user.username,
                )
            )

            if not rows:
                not_found.append(container)
                logger.info(f"Контейнер не найден: {container}")
                continue

            found_rows.append(list(rows[0]))
            logger.info(f"Контейнер найден: {container}")

        await session.commit()

    # Несколько контейнеров → Excel
    if len(containers) > 1 and found_rows:
        try:
            file_path = create_excel_file(found_rows, COLUMNS)
            filename = get_vladivostok_filename()
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
            logger.info(f"Отправлен Excel с дислокацией по {len(found_rows)} контейнерам пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки Excel пользователю {user_id}: {e}", exc_info=True)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # Один контейнер
    if found_rows:
        msg = _format_single_message(found_rows[0])
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        logger.info(f"Дислокация контейнера {found_rows[0][0]} отправлена пользователю {user_id}")
        return

    # Ничего не нашли
    logger.info(f"Ничего не найдено по введённым номерам для пользователя {user_id}")
    await update.message.reply_text("Ничего не найдено по введённым номерам.")