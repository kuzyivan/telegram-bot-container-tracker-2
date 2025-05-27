import tempfile
import pandas as pd
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
import re
from models import Tracking, Stats
from db import SessionLocal
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
    if found_rows:
        row = found_rows[0]
        wagon_number = str(row[9]) if row[9] else "—"
        wagon_type = "полувагон" if wagon_number.startswith("6") else "платформа"
        try:
            km_left = float(row[7])
            forecast_days_calc = round(km_left / 600 + 1, 1)
        except Exception:
            km_left = "—"
            forecast_days_calc = "—"

        msg = (
            f"Контейнер: {row[0]}\n\n"
            f"Маршрут:\n{row[1]} → {row[2]}\n\n"
            f"Текущая станция: {row[3]}\n"
            f"Последняя операция:\n"
            f"{row[5]} — {row[4]}\n\n"
            f"Вагон: {wagon_number} ({wagon_type})\n"
            f"Осталось ехать: {km_left} км\n\n"
            f"Оценка времени в пути:\n~{forecast_days_calc} суток (расчет: {km_left} км / 600 км/сутки + 1 день)"
        )
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
