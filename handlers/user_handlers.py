from telegram import Update
from telegram.ext import ContextTypes
from utils.keyboards import (
    reply_keyboard,
    dislocation_inline_keyboard,
    tracking_inline_keyboard,
    main_menu_keyboard
)
from telegram.error import BadRequest

import re
from models import Tracking, Stats
from db import SessionLocal
from sqlalchemy.future import select
from logger import get_logger

logger = get_logger(__name__)

COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

# /start — всегда reply-клавиатура
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start от пользователя {update.effective_user.id}")
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_keyboard
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Показ главного меню пользователю {update.effective_user.id}")
    if update.message:
        await update.message.reply_text(
            "Главное меню. Выберите действие:",
            reply_markup=reply_keyboard
        )
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "Главное меню. Выберите действие:",
                reply_markup=None
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                await update.callback_query.answer("Меню уже открыто", show_alert=False)
            else:
                logger.error(f"Ошибка при показе меню: {e}", exc_info=True)
                raise

# ReplyKeyboard обработчик (кнопки снизу)
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"reply_keyboard_handler: пользователь {update.effective_user.id} нажал '{text}'")
    if text == "📦 Дислокация":
        await update.message.reply_text(
            "Для поиска контейнера нажмите кнопку ниже:",
            reply_markup=dislocation_inline_keyboard
        )
    elif text == "🔔 Задать слежение":
        await update.message.reply_text(
            "Для постановки на слежение нажмите кнопку ниже:",
            reply_markup=tracking_inline_keyboard
        )
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        return await cancel_tracking_start(update, context)
    else:
        logger.info(f"Не команда меню — ищем '{text}' как обычный запрос контейнера.")
        await handle_message(update, context)
    
# Inline-кнопки меню (start/dislocation/track_request)
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    logger.info(f"menu_button_handler: пользователь {query.from_user.id} выбрал {data}")
    try:
        if data == 'start':
            await query.answer()
            await query.edit_message_text(
                text="Главное меню. Выберите действие:",
                reply_markup=main_menu_keyboard
            )
        elif data == 'dislocation':
            await query.answer()
            await query.edit_message_text(
                text="Введите номер контейнера для получения дислокации."
            )
        elif data == 'track_request':
            from handlers.tracking_handlers import ask_containers
            return await ask_containers(update, context)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("Меню уже открыто", show_alert=False)
        else:
            logger.error(f"Ошибка обработки inline-кнопки: {e}", exc_info=True)
            raise

# Inline-кнопка "Ввести контейнер" для дислокации
async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"dislocation_inline_callback_handler: пользователь {update.effective_user.id}")
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Введите номер контейнера для поиска:")
    # Дальше срабатывает handle_message

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    logger.info(f"handle_sticker: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')
    await show_menu(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else "—"
    user_name = user.username if user else "—"
    logger.info(f"handle_message: пользователь {user_id} ({user_name}) отправил сообщение")
    if not update.message or not update.message.text:
        logger.warning(f"handle_message: пустой ввод от пользователя {user_id}")
        await update.message.reply_text("⛔ Пожалуйста, отправь текстовый номер контейнера.")
        await show_menu(update, context)
        return

    user_input = update.message.text
    logger.info(f"Обрабатываем ввод: {user_input}")
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]
    found_rows = []
    not_found = []

    async with SessionLocal() as session:
        for container_number in container_numbers:
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
            results = result.fetchall()

            stats_record = Stats(
                container_number=container_number,
                user_id=update.message.from_user.id,
                username=update.message.from_user.username
            )
            session.add(stats_record)
            await session.commit()

            if not results:
                not_found.append(container_number)
                logger.info(f"Контейнер не найден: {container_number}")
                continue

            row = results[0]
            found_rows.append(list(row))
            logger.info(f"Контейнер найден: {container_number}")

    # Несколько контейнеров — Excel файл
    if len(container_numbers) > 1 and found_rows:
        from utils.send_tracking import create_excel_file, get_vladivostok_filename

        file_path = create_excel_file(found_rows, COLUMNS)
        filename = get_vladivostok_filename()
        try:
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
            logger.info(f"Отправлен Excel с дислокацией по {len(found_rows)} контейнерам пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки Excel пользователю {user_id}: {e}", exc_info=True)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        await show_menu(update, context)
        return

    # Один контейнер — красивый ответ
    elif found_rows:
        row = found_rows[0]
        wagon_number = str(row[9]) if row[9] else "—"
        wagon_type = "полувагон" if wagon_number.startswith("6") else "платформа"

        try:
            km_left = float(row[7])
            forecast_days_calc = round(km_left / 600 + 1, 1)
        except Exception:
            km_left = "—"
            forecast_days_calc = "—"

        operation_station = f"{row[3]} 🛤️ ({row[10]})" if row[10] else row[3]

        msg = (
            f"📦 <b>Контейнер</b>: <code>{row[0]}</code>\n\n"
            f"🛤 <b>Маршрут</b>:\n"
            f"<b>{row[1]}</b> 🚂 → <b>{row[2]}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>:\n"
            f"{row[5]} — <i>{row[4]}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{wagon_number}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{km_left}</b> км\n\n"
            f"⏳ <b>Оценка времени в пути</b>:\n"
            f"~<b>{forecast_days_calc}</b> суток "
            f"(расчет: {km_left} км / 600 км/сутки + 1 день)"
        )

        await update.message.reply_text(msg, parse_mode="HTML")
        logger.info(f"Дислокация контейнера {row[0]} отправлена пользователю {user_id}")
        await show_menu(update, context)
    else:
        logger.info(f"Ничего не найдено по введённым номерам для пользователя {user_id}")
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
        await show_menu(update, context)