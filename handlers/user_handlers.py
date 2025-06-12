import re
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from sqlalchemy.future import select

from db import SessionLocal
from models import Tracking, Stats
from utils.keyboards import (
    reply_keyboard,
    dislocation_inline_keyboard,
    tracking_inline_keyboard,
    main_menu_keyboard
)
# Перемещаем импорт в начало файла для лучшей практики
from handlers.tracking_handlers import ask_containers, cancel_tracking_start
from utils.send_tracking import create_excel_file, get_vladivostok_filename

COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

# /start — стартовое сообщение
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text(
        "Добро пожаловать! Я помогу вам отследить контейнеры.\nВыберите действие:",
        reply_markup=reply_keyboard
    )

# /menu — показать главное меню
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=reply_keyboard
        )
    elif update.callback_query:
        # Избегаем ошибки "Message is not modified"
        if update.callback_query.message.reply_markup is None:
            await update.callback_query.answer("Меню уже открыто", show_alert=False)
            return
        
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Главное меню:",
            reply_markup=None # Убираем inline-кнопки
        )

# Обработчик кнопок reply-клавиатуры
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text(
            "Нажмите кнопку ниже, чтобы ввести номер контейнера, или просто отправьте его в чат.",
            reply_markup=dislocation_inline_keyboard
        )
    elif text == "🔔 Задать слежение":
        await update.message.reply_text(
            "Нажмите кнопку ниже, чтобы настроить ежедневную рассылку.",
            reply_markup=tracking_inline_keyboard
        )
    elif text == "❌ Отмена слежения":
        await cancel_tracking_start(update, context)

# Обработчик inline-кнопок из главного меню
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'start':
        await query.edit_message_text(
            text="Главное меню:",
            reply_markup=main_menu_keyboard
        )
    elif query.data == 'dislocation':
        await query.edit_message_text(
            text="Введите номер контейнера для получения дислокации."
        )
    elif query.data == 'track_request':
        await ask_containers(update, context)

# Обработчик для кнопки "Ввести контейнер" (дислокация)
async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Введите номер или номера контейнеров для поиска (через пробел, запятую или с новой строки).")

# Обработчик стикеров
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = update.message.sticker.file_id
    await update.message.reply_text(f"Какой забавный стикер! Его ID: `{sticker_id}`", parse_mode='Markdown')

# ОСНОВНОЙ ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("⛔ Пожалуйста, отправьте текстовый номер контейнера.")
        return

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+', user_input.strip()) if c]
    
    if not container_numbers:
        await update.message.reply_text("Не удалось распознать номера контейнеров. Попробуйте еще раз.")
        return

    found_rows = []
    not_found = []
    
    async with SessionLocal() as session:
        # Получаем данные по всем запрошенным контейнерам одним запросом
        result = await session.execute(
            select(Tracking).where(Tracking.container_number.in_(container_numbers))
        )
        found_tracks = result.scalars().all()
        found_map = {track.container_number: track for track in found_tracks}

        # Логируем статистику
        for cn in container_numbers:
            stats_record = Stats(
                container_number=cn,
                user_id=update.message.from_user.id,
                username=update.message.from_user.username
            )
            session.add(stats_record)
        
        await session.commit()

        for cn in container_numbers:
            if cn in found_map:
                track = found_map[cn]
                found_rows.append([
                    track.container_number, track.from_station, track.to_station,
                    track.current_station, track.operation, 
                    track.operation_date.strftime('%Y-%m-%d %H:%M:%S') if track.operation_date else '', 
                    track.waybill, track.km_left, track.forecast_days,
                    track.wagon_number, track.operation_road
                ])
            else:
                not_found.append(cn)
    
    # Ответ для нескольких контейнеров (Excel)
    if len(container_numbers) > 1:
        if found_rows:
            # ВЫНОСИМ БЛОКИРУЮЩУЮ ОПЕРАЦИЮ В EXECUTOR
            loop = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(None, create_excel_file, found_rows, COLUMNS)
            
            filename = get_vladivostok_filename()
            await update.message.reply_document(document=open(file_path, "rb"), filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    # Ответ для одного контейнера (текст)
    if found_rows:
        row = found_rows[0]
        # ... (код для формирования красивого текстового сообщения остается прежним)
        msg = f"📦 <b>Контейнер</b>: <code>{row[0]}</code>\n..." # Сокращено для примера
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")

