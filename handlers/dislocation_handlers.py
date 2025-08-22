from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlalchemy import select
import re

from logger import get_logger
from db import SessionLocal
from models import Tracking, Stats

# train lookup (queries layer preferred, fallback to db)
try:
    from queries.containers import get_latest_train_by_container  # preferred
except Exception:
    from db import get_latest_train_by_container  # fallback

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


# Колонки для выгрузки в Excel (используются при множественных контейнерах)
COLUMNS = [
    'Номер контейнера', 'Поезд',
    'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главная рабочая функция поиска контейнеров:
    - принимает текст (один или несколько номеров),
    - ищет последние записи в Tracking,
    - если >1 контейнера — формирует Excel и отправляет,
    - если 1 — отрисовывает карточку с данными,
    - пишет в Stats каждое обращение.
    """
    user = update.effective_user
    user_id = user.id if user else "—"
    user_name = user.username if user else "—"
    logger.info(f"[dislocation] пользователь {user_id} ({user_name}) отправил сообщение")

    if not update.message or not update.message.text:
        logger.warning(f"[dislocation] пустой ввод от пользователя {user_id}")
        await update.message.reply_text("⛔ Пожалуйста, отправьте текстовый номер контейнера.")
        return

    user_input = update.message.text
    logger.info(f"[dislocation] Обрабатываем ввод: {user_input}")

    # Разбор списка номеров: пробелы/запятые/точки/перевод строки
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]
    found_rows = []
    not_found = []

    async with SessionLocal() as session:
        for container_number in container_numbers:
            # Последняя запись по контейнеру
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
                    Tracking.operation_road
                ).where(
                    Tracking.container_number == container_number
                ).order_by(
                    Tracking.operation_date.desc()
                )
            )
            rows = result.fetchall()

            # Логируем факт запроса
            stats_record = Stats(
                container_number=container_number,
                user_id=update.message.from_user.id,
                username=update.message.from_user.username
            )
            session.add(stats_record)
            await session.commit()

            if not rows:
                not_found.append(container_number)
                logger.info(f"[dislocation] Контейнер НЕ найден: {container_number}")
                continue

            row = rows[0]
            found_rows.append(list(row))
            logger.info(f"[dislocation] Контейнер найден: {container_number}")

    # === Если пользователь прислал несколько контейнеров ===
    if len(container_numbers) > 1 and found_rows:
        try:
            # Строим строки для Excel с дополнительной колонкой "Поезд"
            rows_for_excel = []
            for row in found_rows:
                container = row[0]
                # подгружаем поезд для каждой строки
                try:
                    train = await get_latest_train_by_container(container)
                except Exception as e:
                    logger.error(f"[dislocation][excel] Ошибка получения train для {container}: {e}", exc_info=True)
                    train = None

                # раскладываем значения из row (как выбирали из Tracking)
                from_station      = row[1]
                to_station        = row[2]
                current_station   = row[3]
                operation         = row[4]
                operation_date    = row[5]
                waybill           = row[6]
                km_left           = row[7]
                forecast_days     = row[8]
                wagon_number      = row[9]
                operation_road    = row[10]

                rows_for_excel.append([
                    container,
                    train or "",               # Поезд
                    from_station,
                    to_station,
                    current_station,
                    operation,
                    operation_date,
                    km_left,
                    forecast_days,
                    wagon_number,
                    operation_road,
                ])

            from utils.send_tracking import create_excel_file, get_vladivostok_filename  # локальный импорт
            file_path = create_excel_file(rows_for_excel, COLUMNS)
            filename = get_vladivostok_filename()
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
            logger.info(f"[dislocation] Excel с дислокацией по {len(found_rows)} контейнерам отправлен пользователю {user_id}")
        except Exception as e:
            logger.error(f"[dislocation] Ошибка отправки Excel пользователю {user_id}: {e}", exc_info=True)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # === Один контейнер найден ===
    if found_rows:
        row = found_rows[0]

        # Получаем номер поезда из terminal_containers по самой свежей записи
        try:
            train = await get_latest_train_by_container(row[0])
        except Exception as e:
            logger.error(f"[dislocation] Ошибка получения train для {row[0]}: {e}", exc_info=True)
            train = None

        wagon_number = str(row[9]) if row[9] else "—"
        wagon_type = detect_wagon_type(wagon_number)

        try:
            km_left_val = float(row[7])
            forecast_days_calc = round(km_left_val / 600 + 1, 1)
            km_left_display = km_left_val
        except Exception:
            km_left_display = "—"
            forecast_days_calc = "—"

        operation_station = f"{row[3]} 🛤️ ({row[10]})" if row[10] else row[3]

        # Шапка с контейнером и (если найден) номером поезда
        header = f"📦 <b>Контейнер</b>: <code>{row[0]}</code>\n"
        if train:
            header += f"🚂 <b>Поезд</b>: <code>{train}</code>\n"
        header += "\n"

        msg = (
            f"{header}"
            f"🛤 <b>Маршрут</b>:\n"
            f"<b>{row[1]}</b> 🚂 → <b>{row[2]}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>:\n"
            f"{row[5]} — <i>{row[4]}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{_fmt_num(wagon_number)}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{_fmt_num(km_left_display)}</b> км\n\n"
            f"⏳ <b>Оценка времени в пути</b>:\n"
            f"~<b>{_fmt_num(forecast_days_calc)}</b> суток "
            f"(расчёт: {_fmt_num(km_left_display)} км / 600 км/сутки + 1 день)"
        )

        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        logger.info(f"[dislocation] Карточка по контейнеру {row[0]} отправлена пользователю {user_id}")
        return

    # === Ничего не найдено ===
    logger.info(f"[dislocation] Ничего не найдено по введённым номерам для пользователя {user_id}")
    await update.message.reply_text("Ничего не найдено по введённым номерам.")