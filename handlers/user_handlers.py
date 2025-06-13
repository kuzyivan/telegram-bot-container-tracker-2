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

# ... (код до handle_message без изменений) ...
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_keyboard
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                reply_markup=main_menu_keyboard
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                await update.callback_query.answer("Меню уже открыто", show_alert=False)
            else:
                raise

# ReplyKeyboard обработчик (кнопки снизу)
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text(
            "Введите номер контейнера для получения дислокации."
        )
    elif text == "🔔 Задать слежение":
        from handlers.tracking_handlers import ask_containers
        # Этот вызов не будет работать напрямую, т.к. ConversationHandler ждет CallbackQuery
        # Лучше направить пользователя на inline-кнопку
        await update.message.reply_text(
            "Для постановки на слежение нажмите кнопку ниже:",
            reply_markup=tracking_inline_keyboard
        )
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        return await cancel_tracking_start(update, context)
    else:
        await handle_message(update, context)
    
# Inline-кнопки меню (start/dislocation/track_request)
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    try:
        if data == 'start':
            await query.edit_message_text(
                text="Главное меню. Выберите действие:",
                reply_markup=main_menu_keyboard
            )
        elif data == 'dislocation':
            await query.edit_message_text(
                text="Введите номер контейнера для получения дислокации."
            )
        elif data == 'track_request':
            from handlers.tracking_handlers import ask_containers
            return await ask_containers(update, context) # Это правильный вызов для ConversationHandler
    except BadRequest as e:
        if "Message is not modified" not in str(e):
             raise

# Inline-кнопка "Ввести контейнер" для дислокации
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

    found_rows = []
    not_found = list(container_numbers)

    async with SessionLocal() as session:
        # Один запрос для всех контейнеров
        results = await session.execute(
            select(Tracking).where(Tracking.container_number.in_(container_numbers))
        )
        
        # Запись статистики
        user = update.message.from_user
        stats_records = [Stats(container_number=cn, user_id=user.id, username=user.username) for cn in container_numbers]
        session.add_all(stats_records)
        await session.commit()

        for row in results.scalars().all():
            found_rows.append(list(row.tuple())) # Преобразуем в кортеж и затем в список
            if row.container_number in not_found:
                not_found.remove(row.container_number)
    
    COLUMNS = [
        'Номер контейнера', 'Станция отправления', 'Станция назначения',
        'Станция операции', 'Операция', 'Дата и время операции',
        'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
        'Номер вагона', 'Дорога операции'
    ]

    # Несколько контейнеров или один, но в виде Excel
    if len(container_numbers) > 1 and found_rows:
        from utils.send_tracking import create_excel_file, get_vladivostok_filename
        file_path = create_excel_file(found_rows, COLUMNS)
        filename = get_vladivostok_filename()
        
        # Исправлено: используется with
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # Один контейнер — красивый ответ
    elif found_rows:
        row = found_rows[0]
        # ... (код формирования красивого ответа без изменений)
        wagon_number = str(row[9]) if row[9] else "—"
        wagon_type = "полувагон" if wagon_number.startswith("6") else "платформа"

        try:
            km_left = float(row[7])
            forecast_days_calc = round(km_left / 600 + 1, 1)
        except (ValueError, TypeError):
            km_left = "—"
            forecast_days_calc = "—"

        operation_station = f"{row[3]} ({row[10]})" if row[10] else row[3]

        msg = (
            f"📦 <b>Контейнер</b>: <code>{row[0]}</code>\n\n"
            f"🛤 <b>Маршрут</b>: <b>{row[1]}</b> → <b>{row[2]}</b>\n\n"
            f"📍 <b>Текущая станция</b>: {operation_station}\n"
            f"📅 <b>Последняя операция</b>: {row[5]} — <i>{row[4]}</i>\n\n"
            f"🚆 <b>Вагон</b>: <code>{wagon_number}</code> ({wagon_type})\n"
            f"📏 <b>Осталось ехать</b>: <b>{km_left}</b> км\n"
            f"⏳ <b>Оценка времени в пути</b>: ~<b>{forecast_days_calc}</b> суток"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    if not_found:
        await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))

