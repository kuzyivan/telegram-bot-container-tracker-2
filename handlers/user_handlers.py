import tempfile
import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
import re
from models import Tracking, Stats
from db import SessionLocal
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from handlers.tracking_handlers import send_tracking_notifications

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📦 Поставить на слежение", callback_data="track_request")],
    ]
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def testnotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Можно передать любое время (например, "16:00")
    await send_tracking_notifications(context.bot, "16:00")
    await update.message.reply_text("Тестовая рассылка выполнена (как будто сейчас 16:00).")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("⛔ Пожалуйста, отправь текстовый номер контейнера.")
        return

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]
    found_rows = []
    not_found = []

    with SessionLocal() as session:
        for container_number in container_numbers:
            results = session.query(
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
            ).filter(
                Tracking.container_number == container_number
            ).order_by(
                Tracking.operation_date.desc()
            ).all()

            stats_record = Stats(
                container_number=container_number,
                user_id=update.message.from_user.id,
                username=update.message.from_user.username
            )
            session.add(stats_record)
            session.commit()

            if not results:
                not_found.append(container_number)
                continue

            row = results[0]
            found_rows.append([
                row.container_number,
                row.from_station,
                row.to_station,
                row.current_station,
                row.operation,
                row.operation_date,
                row.waybill,
                row.km_left,
                row.forecast_days,
                row.wagon_number,
                row.operation_road
            ])

    # Несколько контейнеров — Excel файл
    if len(container_numbers) > 1 and found_rows:
        df = pd.DataFrame(found_rows, columns=[
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Дислокация')
                fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                worksheet = writer.sheets['Дислокация']
                for cell in worksheet[1]:
                    cell.fill = fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

            vladivostok_time = datetime.utcnow() + timedelta(hours=10)
            filename = f"Дислокация {vladivostok_time.strftime('%H-%M')}.xlsx"
            await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)

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

        # Расшифровка дороги (если есть)
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
