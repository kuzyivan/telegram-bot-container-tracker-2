import re
import tempfile
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from db import get_pg_connection

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = "CAACAgIAAxkBAAIC6mgUWmOtztmC0dnqI3C2l4wcikA-AAJvbAACa_OZSGYOhHaiIb7mNgQ"
    await update.message.reply_sticker(sticker_id)
    await update.message.reply_text("Привет! Отправь мне номер контейнера для отслеживания.")

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    await update.message.reply_text(f"🆔 ID этого стикера:\n`{sticker.file_id}`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]

    conn = get_pg_connection()
    cursor = conn.cursor()

    found_rows = []
    not_found = []

    for number in container_numbers:
        cursor.execute("""
            SELECT container_number, from_station, to_station, current_station,
                   operation, operation_date, waybill, km_left, forecast_days,
                   wagon_number, operation_road
            FROM tracking WHERE container_number = %s
        """, (number,))
        row = cursor.fetchone()
        if row:
            found_rows.append(row)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    id SERIAL PRIMARY KEY,
                    container_number TEXT,
                    user_id BIGINT,
                    username TEXT,
                    timestamp TIMESTAMP DEFAULT NOW()
                )
            """)
            cursor.execute("""
                INSERT INTO stats (container_number, user_id, username)
                VALUES (%s, %s, %s)
            """, (number, update.message.from_user.id, update.message.from_user.username))
            conn.commit()
        else:
            not_found.append(number)

    conn.close()

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
                from openpyxl.styles import PatternFill
                fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                worksheet = writer.sheets['Дислокация']
                for cell in worksheet[1]:
                    cell.fill = fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

            from datetime import datetime, timedelta
            vladivostok_time = datetime.utcnow() + timedelta(hours=10)
            filename = f"Дислокация {vladivostok_time.strftime('%H-%M')}.xlsx"
            await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)

        if not_found:
            await update.message.reply_text("❌ Не найдены: " + ", ".join(not_found))
        return

    if found_rows:
        reply_lines = []
        for row in found_rows:
            wagon_type = "полувагон" if row[9].startswith("6") else "платформа"
            reply_lines.append(
                f"🚛 Контейнер: {row[0]}\n"
                f"🚇 Вагон: {row[9]} {wagon_type}\n"
                f"📍Дислокация: {row[3]} {row[10]}\n"
                f"🏗 Операция: {row[4]}\n📅 {row[5]}\n\n"
                f"Откуда: {row[1]}\nКуда: {row[2]}\n\n"
                f"Накладная: {row[6]}\nОсталось км: {row[7]}\n"
                f"📅 Прогноз прибытия: {row[8]} дн."
            )
        await update.message.reply_text("\n" + "═" * 30 + "\n".join(reply_lines))
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
