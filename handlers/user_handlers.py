import pandas as pd
import re
from models import Tracking, Stats
from db import SessionLocal
from telegram import Update
from telegram.ext import ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("⛔ Пожалуйста, отправь текстовый номер контейнера.")
        return

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]

    reply_messages = []

    with SessionLocal() as session:
        for container_number in container_numbers:
            results = session.query(
                Tracking.container_number,
                Tracking.current_station,
                Tracking.operation_date,
                Tracking.operation,
                Tracking.wagon_number,
                Tracking.from_station,
                Tracking.to_station,
                Tracking.km_left,
                Tracking.forecast_days
            ).filter(
                Tracking.container_number == container_number
            ).all()

            # Запись в stats
            stats_record = Stats(
                container_number=container_number,
                user_id=update.message.from_user.id,
                username=update.message.from_user.username
            )
            session.add(stats_record)
            session.commit()

            if not results:
                reply_messages.append(f"🤷 Контейнер {container_number} не найден.")
                continue

            df = pd.DataFrame([{
                'Номер контейнера': row.container_number,
                'Текущая станция': row.current_station,
                'Дата операции': row.operation_date,
                'Операция': row.operation,
                'Номер вагона': row.wagon_number,
                'Тип вагона': "полувагон" if row.wagon_number and str(row.wagon_number).startswith("6") else "платформа",
                'Станция отправления': row.from_station,
                'Станция назначения': row.to_station,
                'Расстояние, км': row.km_left,
                'Прогноз дней': row.forecast_days
            } for row in results])

            message = df.to_string(index=False)
            reply_messages.append(
                f"🔍 Данные по контейнеру {container_number}:\n\n```\n{message}\n```"
            )

    # Ограничение на длину сообщения Telegram — 4096 символов!
    for reply in reply_messages:
        for part in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
            await update.message.reply_text(part, parse_mode='Markdown')
