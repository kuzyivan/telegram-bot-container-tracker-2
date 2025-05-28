import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from datetime import datetime, timedelta
from openpyxl.styles import PatternFill
from sqlalchemy.orm import Session
from db import engine
from db import SessionLocal
from models import TrackingSubscription
import tempfile

# /tracking — выгрузка всех подписок на слежение в Excel
async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    with SessionLocal() as session:
        subs = session.query(TrackingSubscription).all()
        if not subs:
            await update.message.reply_text("Нет активных слежений.")
            return

        data = [
            {
                "user_id": s.user_id,
                "username": s.username,
                "containers": s.containers,
                "time": s.notify_time,
            }
            for s in subs
        ]
        df = pd.DataFrame(data)
        with tempfile.NamedTemporaryFile("wb", suffix=".xlsx", delete=False) as tmp:
            df.to_excel(tmp.name, index=False)
            tmp.flush()
            await update.message.reply_document(document=open(tmp.name, "rb"), filename="tracking_subs.xlsx")

# /stats — статистика запросов за последние сутки в текстовом виде
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    with Session(engine) as session:
        query = """
            SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
                   STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
            FROM stats
            WHERE timestamp >= NOW() - INTERVAL '1 day'
              AND user_id != %s
            GROUP BY user_id, username
            ORDER BY запросов DESC
        """
        df = pd.read_sql_query(query, session.bind, params=(ADMIN_CHAT_ID,))

    if df.empty:
        await update.message.reply_text("Нет статистики за последние сутки.")
        return

    text = "📊 Статистика за последние 24 часа:\n\n"
    messages = []

    for _, row in df.iterrows():
        entry = (
            f"👤 {row['username']} (ID: {row['user_id']})\n"
            f"Запросов: {row['запросов']}\n"
            f"Контейнеры: {row['контейнеры']}\n\n"
        )
        if len(text) + len(entry) > 4000:
            messages.append(text)
            text = ""
        text += entry
    messages.append(text)

    for msg in messages:
        await update.message.reply_text(msg)

# /exportstats — Excel выгрузка всех запросов за всё время (кроме админа)
async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    with Session(engine) as session:
        df = pd.read_sql_query(
            "SELECT * FROM stats WHERE user_id::text != %s",
            session.bind,
            params=(ADMIN_CHAT_ID,)
        )

    if df.empty:
        await update.message.reply_text("Нет данных для экспорта.")
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Статистика')
            worksheet = writer.sheets['Статистика']

            header_fill = PatternFill(start_color='FFD673', end_color='FFD673', fill_type='solid')
            for cell in worksheet[1]:
                cell.fill = header_fill
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_length + 2

        vladivostok_time = datetime.utcnow() + timedelta(hours=10)
        filename = f"Статистика {vladivostok_time.strftime('%H-%M')}.xlsx"
        await update.message.reply_document(document=open(tmp.name, "rb"), filename=filename)
