from telegram import Update
from telegram.ext import ContextTypes
import re
from db.models import Tracking, Stats, SessionLocal

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("⛔ Пожалуйста, отправь текстовый номер контейнера.")
        return

    user_input = update.message.text
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\n.]+' , user_input.strip()) if c]

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
            ).order_by(
                Tracking.operation_date.desc()
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
                await update.message.reply_text(f"🤷 Контейнер {container_number} не найден.")
                continue

            # Берём последнюю операцию
            row = results[0]

            # Тип вагона
            wagon_type = "полувагон" if row.wagon_number and str(row.wagon_number).startswith("6") else "платформа"

            # Оценка времени (осталось км / 600 + 1)
            try:
                km_left = float(row.km_left)
                forecast_days_calc = round(km_left / 600 + 1, 1)
            except Exception:
                km_left = "—"
                forecast_days_calc = "—"

            # Формируем красивый ответ
            msg = (
                f"Контейнер: {row.container_number}\n\n"
                f"Маршрут:\n{row.from_station} → {row.to_station}\n\n"
                f"Текущая станция: {row.current_station}\n"
                f"Последняя операция:\n"
                f"{row.operation_date} — {row.operation}\n\n"
                f"Вагон: {row.wagon_number} ({wagon_type})\n"
                f"Осталось ехать: {row.km_left} км\n\n"
                f"Оценка времени в пути:\n~{forecast_days_calc} суток "
                f"(расчет: {row.km_left} км / 600 км/сутки + 1 день)"
            )

            await update.message.reply_text(msg)

