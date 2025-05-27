import pandas as pd
from models import Tracking, Stats
from db import SessionLocal

async def handle_message(update, context):
    container_number = update.message.text.strip().upper()

    with SessionLocal() as session:
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

        # Сохраняем запись статистики
        stats_record = Stats(
            container_number=container_number,
            user_id=update.message.from_user.id,
            username=update.message.from_user.username
        )
        session.add(stats_record)
        session.commit()

    if not results:
        await update.message.reply_text(f"🤷 Контейнер {container_number} не найден.")
        return

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
    await update.message.reply_text(
        f"🔍 Вот данные по контейнеру:\n\n```\n{message}\n```",
        parse_mode='Markdown'
    )
