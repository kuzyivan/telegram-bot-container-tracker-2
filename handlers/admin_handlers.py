import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from sqlalchemy import text
from sqlalchemy.future import select
from db import SessionLocal
from models import TrackingSubscription, Tracking

# Универсальный экспорт Excel
from utils.send_tracking import create_excel_file, create_excel_multisheet, get_vladivostok_filename

# /tracking — выгрузка всех подписок на слежение в Excel
async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    async with SessionLocal() as session:
        result = await session.execute(text("SELECT * FROM tracking_subscriptions"))
        subs = result.fetchall()
        if not subs:
            await update.message.reply_text("Нет активных слежений.")
            return

        columns = result.keys()
        df = pd.DataFrame(subs, columns=columns)
        file_path = create_excel_file(df.values.tolist(), list(df.columns))
        filename = get_vladivostok_filename().replace("Дислокация", "tracking_subs")
        
        # Исправлено: используется with для безопасного открытия файла
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)

# /stats — статистика запросов за последние сутки в текстовом виде
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    async with SessionLocal() as session:
        query = text("""
            SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
                   STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
            FROM stats
            WHERE timestamp >= NOW() - INTERVAL '1 day'
              AND user_id != :admin_id
            GROUP BY user_id, username
            ORDER BY запросов DESC
        """)
        result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
        rows = result.fetchall()

    if not rows:
        await update.message.reply_text("Нет статистики за последние сутки.")
        return

    text_msg = "📊 Статистика за последние 24 часа:\n\n"
    # ... (остальной код без изменений)
    for row in rows:
        entry = (
            f"👤 {row.username} (ID: {row.user_id})\n"
            f"Запросов: {row.запросов}\n"
            f"Контейнеры: {row.контейнеры}\n\n"
        )
        text_msg += entry
    await update.message.reply_text(text_msg)


# /exportstats — Excel выгрузка всех запросов за всё время (кроме админа)
async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    async with SessionLocal() as session:
        query = text("SELECT * FROM stats WHERE user_id != :admin_id")
        result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
        rows = result.fetchall()

    if not rows:
        await update.message.reply_text("Нет данных для экспорта.")
        return

    columns = result.keys()
    df = pd.DataFrame(rows, columns=columns)
    file_path = create_excel_file(df.values.tolist(), list(df.columns))
    filename = get_vladivostok_filename().replace("Дислокация", "Статистика")

    # Исправлено: используется with
    with open(file_path, "rb") as f:
        await update.message.reply_document(document=f, filename=filename)

# /testnotify — один Excel, все подписки, каждый пользователь отдельным листом
async def test_notify(update, context):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    async with SessionLocal() as session:
        result = await session.execute(select(TrackingSubscription))
        subscriptions = result.scalars().all()
        
        all_containers = {c for sub in subscriptions for c in sub.containers}
        
        tracking_data = {}
        if all_containers:
            res = await session.execute(select(Tracking).where(Tracking.container_number.in_(all_containers)))
            tracking_data = {t.container_number: t for t in res.scalars().all()}

        columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ]
        data_per_user = {}

        for sub in subscriptions:
            user_label = f"{sub.username or sub.user_id}"
            rows = []
            for container in sub.containers:
                track = tracking_data.get(container)
                if track:
                    rows.append([
                        track.container_number, track.from_station, track.to_station,
                        track.current_station, track.operation, track.operation_date,
                        track.waybill, track.km_left, track.forecast_days,
                        track.wagon_number, track.operation_road
                    ])
            data_per_user[user_label] = rows if rows else [["Нет данных"] + [""] * (len(columns)-1)]

        file_path = create_excel_multisheet(data_per_user, columns)
        filename = get_vladivostok_filename("Тестовая дислокация")
        
        # Исправлено: используется with
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="Тестовая дислокация по всем подписчикам (разделено по листам)"
            )
