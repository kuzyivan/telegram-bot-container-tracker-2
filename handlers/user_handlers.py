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
from utils.send_tracking import create_excel_file, get_vladivostok_filename

# ... (код start, show_menu, reply_keyboard_handler, menu_button_handler, dislocation_inline_callback_handler, handle_sticker - без изменений) ...

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_keyboard
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_message = update.message or (update.callback_query and update.callback_query.message)
    if not target_message:
        return

    # Отправляем новое сообщение с клавиатурой, если это текстовая команда,
    # или пытаемся отредактировать, если это callback от inline-кнопки.
    if update.message:
        await target_message.reply_text(
            "Главное меню:",
            reply_markup=reply_keyboard
        )
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                "Главное меню. Выберите действие:",
                reply_markup=main_menu_keyboard
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                # Если сообщение не изменилось, просто игнорируем. Иначе отправляем новое.
                await target_message.reply_text(
                    "Главное меню:",
                    reply_markup=reply_keyboard
                )

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text(
            "Введите номер контейнера для получения дислокации."
        )
    elif text == "🔔 Задать слежение":
        await update.message.reply_text(
            "Для постановки на слежение нажмите кнопку ниже:",
            reply_markup=tracking_inline_keyboard
        )
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        await cancel_tracking_start(update, context)
    else:
        await handle_message(update, context)
    
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        if data == 'start':
            await query.edit_message_text(
                text="Главное меню. Выберите действие:",
                reply_markup=main_menu_keyboard
            )
        elif data == 'dislocation':
            await query.edit_message_text(text="Введите номер контейнера для получения дислокации.")
        elif data == 'track_request':
            from handlers.tracking_handlers import ask_containers
            await ask_containers(update, context)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
             raise

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Введите номер контейнера для поиска:")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,;\n]+', user_input.strip()) if c.strip()]
    
    if not container_numbers:
        await update.message.reply_text("Пожалуйста, введите корректный номер контейнера.")
        return

    found_tracks = {}
    async with SessionLocal() as session:
        # Один запрос для всех контейнеров
        result = await session.execute(
            select(Tracking).where(Tracking.container_number.in_(container_numbers))
        )
        for track in result.scalars().all():
            found_tracks[track.container_number] = track
        
        # Запись статистики
        user = update.message.from_user
        stats_records = [Stats(container_number=cn, user_id=user.id, username=user.username) for cn in container_numbers]
        session.add_all(stats_records)
        await session.commit()

    not_found = [cn for cn in container_numbers if cn not in found_tracks]

    # Если запрос на несколько контейнеров и что-то найдено -> Excel
    if len(container_numbers) > 1 and found_tracks:
        COLUMNS = ['Номер контейнера', 'Станция отправления', 'Станция назначения', 'Станция операции', 'Операция', 'Дата и время операции', 'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)', 'Номер вагона', 'Дорога операции']
        rows_for_excel = []
        for cn in container_numbers:
            track = found_tracks.get(cn)
            if track:
                rows_for_excel.append([
                    track.container_number, track.from_station, track.to_station,
                    track.current_station, track.operation, track.operation_date,
                    track.waybill, track.km_left, track.forecast_days,
                    track.wagon_number, track.operation_road
                ])
        
        file_path = create_excel_file(rows_for_excel, COLUMNS)
        filename = get_vladivostok_filename()
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)

    # Если запрос на один контейнер и он найден
    elif len(container_numbers) == 1 and container_numbers[0] in found_tracks:
        track = found_tracks[container_numbers[0]]
        wagon_number = str(track.wagon_number) if track.wagon_number else "—"
        wagon_type = "полувагон" if wagon_number.startswith("6") else "платформа"
        km_left = track.km_left if track.km_left is not None else "—"
        forecast_days_calc = f"~<b>{track.forecast_days}</b> суток" if track.forecast_days is not None else "—"
        operation_station = f"{track.current_station} ({track.operation_road})" if track.operation_road else track.current_station

        msg = (
            f"📦 <b>Контейнер</b>: <code>{track.container_number}</code>\n\n"
            f"🛤 <b>Маршрут</b>: <b>{track.from_station}</b> → <b>{track.to_station}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>: {track.operation_date} — <i>{track.operation}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{wagon_number}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{km_left}</b> км\n"
            f"⏳ <b>Прогноз (дни)</b>: {forecast_days_calc}"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    # Сообщаем о ненайденных контейнерах, если они есть
    if not_found:
        await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))

