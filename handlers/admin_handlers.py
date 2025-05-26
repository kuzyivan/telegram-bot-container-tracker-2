import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from db import get_pg_connection
from config import ADMIN_CHAT_ID
from datetime import datetime, timedelta
from openpyxl.styles import PatternFill
import tempfile

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = get_pg_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
               STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
        FROM stats
        WHERE timestamp >= NOW() - INTERVAL '1 day'
          AND user_id != 114419850
        GROUP BY user_id, username
        ORDER BY запросов DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Нет статистики за последние сутки.")
        return

    text = "📊 Статистика за последние 24 часа:\n\n"
    messages = []
    for row in rows:
        entry = (
            f"👤 {row[1]} (ID: {row[0]})\n"
            f"Запросов: {row[2]}\n"
            f"Контейнеры: {row[3]}\n\n"
        )
        if len(text) + len(entry) > 4000:
            messages.append(text)
            text = ""
        text += entry
    messages.append(text)

    for msg in messages:
        await update.message.reply_text(msg)

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    conn = get_pg_connection()
    query = """
        SELECT * FROM stats
        WHERE user_id::text != %s
    """
    df = pd.read_sql_query(query, conn, params=(ADMIN_CHAT_ID,))
    conn.close()

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
