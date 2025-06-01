import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from datetime import datetime, timedelta, time
from sqlalchemy import text
from db import SessionLocal
from models import TrackingSubscription
from scheduler import send_notifications

# Новый импорт для единого экспорта Excel
from utils.send_tracking import create_excel_file, get_vladivostok_filename

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
        data = [dict(zip(columns, row)) for row in subs]
        df = pd.DataFrame(data)
        file_path = create_excel_file(df.values.tolist())  # тут можно использовать create_excel_file для совместимости оформления
        filename = get_vladivostok_filename().replace("Дислокация", "tracking_subs")
        await update.message.reply_document(document=open(file_path, "rb"), filename=filename)

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
    messages = []
    for row in rows:
        entry = (
            f"👤 {row.username} (ID: {row.user_id})\n"
            f"Запросов: {row.запросов}\n"
            f"Контейнеры: {row.контейнеры}\n\n"
        )
        if len(text_msg) + len(entry) > 4000:
            messages.append(text_msg)
            text_msg = ""
        text_msg += entry
    messages.append(text_msg)
    for msg in messages:
        await update.message.reply_text(msg)

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
    file_path = create_excel_file(df.values.tolist(), columns=list(df.columns))  # унифицированная функция
    filename = get_vladivostok_filename().replace("Дислокация", "Статистика")
    await update.message.reply_document(document=open(file_path, "rb"), filename=filename)

# /testnotify — тестовая отправка рассылки админу
async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    await send_notifications(context.bot, time(9, 0))
    await update.message.reply_text("✅ Тестовая рассылка дислокации выполнена.")
