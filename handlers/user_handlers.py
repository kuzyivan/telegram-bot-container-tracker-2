import tempfile
import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from models import Tracking, Stats
from db import SessionLocal
from sqlalchemy.future import select
from utils.keyboards import main_menu_keyboard  # добавлено

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=main_menu_keyboard
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Выберите действие:",
            reply_markup=main_menu_keyboard
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await show_menu(update, context)

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == 'start':
        await query.answer()
        await query.edit_message_text(
            text="Выберите действие:",
            reply_markup=main_menu_keyboard
        )
    elif data == 'dislocation':
        await query.answer()
        await query.edit_message_text(
            text="Введите номер контейнера для получения дислокации."
        )
        # Дальше пользователь вводит контейнер — сработает handle_message
    elif data == 'track_request':
        from handlers.tracking_handlers import ask_containers
        return await ask_containers(update, context)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("⛔ Пожалуйста, отправь текстовый номер контейнера.")
        return

    user_input = update.message.text
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
                continue

            row = results[0]
            found_rows.append(list(row))

    # Несколько контейнеров — Excel файл
    if len(container_numbers) > 1 and found_rows:
        from utils.send_tracking import create_excel_file, get_vladivostok_filename

        if len(container_numbers) > 1 and found_rows:
            file_path = create_excel_file(found_rows)
            filename = get_vladivostok_filename()
            await update.message.reply_document(document=open(file_path, "rb"), filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
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
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
