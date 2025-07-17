from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from utils.keyboards import reply_keyboard
import re
from models import Tracking, Stats
from db import (
    SessionLocal,
    get_all_user_ids,
    get_tracked_containers_by_user,
    remove_user_tracking,
    set_user_email,
)
from sqlalchemy import select
from logger import get_logger

logger = get_logger(__name__)

SET_EMAIL = range(1)

COLUMNS = [
    'Номер контейнера', 'Станция отправления', 'Станция назначения',
    'Станция операции', 'Операция', 'Дата и время операции',
    'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
    'Номер вагона', 'Дорога операции'
]

# Главное меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ]
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text(
        "Привет! Я бот для отслеживания контейнеров 🚢\n"
        "Выберите действие в меню:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True),
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# Email Conversation
async def set_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, отправьте ваш email для уведомлений, или /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove()
    )
    return SET_EMAIL

async def process_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username or ""

    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        await update.message.reply_text("❌ Некорректный email. Попробуй ещё раз или /cancel для отмены.")
        return SET_EMAIL

    await set_user_email(telegram_id, username, email, enable_email=True)
    await update.message.reply_text(
        f"Email {email} успешно сохранён ✅", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cancel_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ввод email отменён.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Обработка reply-клавиатуры
async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Дислокация":
        await update.message.reply_text("Введите номер контейнера для поиска:")
    elif text == "🔔 Задать слежение":
        return  # Передано в ConversationHandler tracking_conversation_handler
    elif text == "❌ Отмена слежения":
        from handlers.tracking_handlers import cancel_tracking_start
        return await cancel_tracking_start(update, context)
    else:
        await update.message.reply_text("Команда не распознана. Используйте кнопки меню.")

# Inline кнопки
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "start":
        await start(query, context)
    elif query.data == "dislocation":
        await query.edit_message_text("Введите номер контейнера для поиска:")
    elif query.data == "track_request":
        await query.edit_message_text("Введите номер контейнера для слежения:")

async def dislocation_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите номер контейнера для поиска:")

# Стикеры
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    logger.info(f"handle_sticker: пользователь {update.effective_user.id} прислал стикер {sticker.file_id}")
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')
    await show_menu(update, context)

# Главная функция поиска контейнеров
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from utils.send_tracking import create_excel_file, get_vladivostok_filename

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

    if len(container_numbers) > 1 and found_rows:
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

# Показать отслеживаемые контейнеры пользователя
async def show_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    containers = await get_tracked_containers_by_user(user_id)
    if containers:
        msg = "Вы отслеживаете контейнеры:\n" + "\n".join(containers)
    else:
        msg = "У вас нет активных подписок на контейнеры."
    await update.message.reply_text(msg)

# Отмена всех подписок пользователя
async def cancel_my_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await remove_user_tracking(user_id)
    await update.message.reply_text("Все подписки успешно отменены.")