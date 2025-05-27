import re
import tempfile
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from db import engine
from models import Tracking, Stats
from openpyxl.styles import PatternFill

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_sticker("CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ")
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]
    found_rows, not_found = [], []

    with Session(engine) as session:
        for number in container_numbers:
            result = session.query(Tracking).filter(Tracking.container_number == number).first()
            if result:
                found_rows.append(result)

                session.add(Stats(
                    container_number=number,
                    user_id=update.message.from_user.id,
                    username=update.message.from_user.username
                ))
                session.commit()
            else:
                not_found.append(number)

    if len(container_numbers) > 1 and found_rows:
        df = pd.DataFrame([{
            'Номер контейнера': row.container_number,
            'Станция отправления': row.from_station,
            'Станция назначения': row.to_station,
            'Станция операции': row.current_station,
            'Операция': row.operation,
            'Дата и время операции': row.operation_date,
            'Номер накладной': row.waybill,
            'Расстояние оставшееся': row.km_left,
            'Прогноз прибытия (дней)': row.forecast_days,
            'Номер вагона': row.wagon_number,
            'Дорога операции': row.operation_road
        } for row in found_rows])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Дислокация')
                worksheet = writer.sheets['Дислокация']
                for cell in worksheet[1]: cell.fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

            filename = f"Дислокация {datetime.utcnow() + timedelta(hours=10):%H-%M}.xlsx"
            await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    if found_rows:
        replies = []
        for row in found_rows:
            wagon_type = "полувагон" if row.wagon_number and row.wagon_number.startswith("6") else "платформа"
            replies.append(
                f"🚛 Контейнер: {row.container_number}\n"
                f"🚇 Вагон: {row.wagon_number or '—'} {wagon_type}\n"
                f"📍Дислокация: {row.current_station} {row.operation_road}\n"
                f"🏗 Операция: {row.operation}\n📅 {row.operation_date}\n\n"
                f"Откуда: {row.from_station}\nКуда: {row.to_station}\n\n"
                f"Накладная: {row.waybill}\nОсталось км: {row.km_left}\n"
                f"📅 Прогноз прибытия: {row.forecast_days} дн."
            )
        await update.message.reply_text("\n" + "═" * 30 + "\n".join(replies))
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
