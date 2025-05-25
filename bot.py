import os
import logging
import threading
import time
import tempfile
import pandas as pd
import psycopg2
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from mail_reader import start_mail_checking, ensure_database_exists
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from openpyxl.styles import PatternFill

# Flask-сервер для пинга Render
ping_app = Flask('ping')
@ping_app.route('/')
def ping_root():
    return 'OK', 200
Thread(target=lambda: ping_app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000))), daemon=True).start()

# Логирование и переменные окружения
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '0'))

# Подключение к БД
def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST'),
        port=int(os.getenv('POSTGRES_PORT', 5432)),
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD')
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Отправь мне номер контейнера для отслеживания.')

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = update.message.sticker.file_id
    await update.message.reply_text(f'🆔 ID стикера:\n`{sid}`', parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Разбиваем ввод пользователя на коды контейнеров
    container_numbers = [c.strip().upper() for c in re.split(r'[\s,\.]+', update.message.text.strip()) if c]
    if not container_numbers:
        return await update.message.reply_text('❌ Неверный ввод. Введите номер контейнера.')

    conn = get_pg_connection(); cur = conn.cursor()
    found_rows, not_found = [], []
    for num in container_numbers:
        cur.execute(
            'SELECT container_number, from_station, to_station, current_station, '
            'operation, operation_date, waybill, km_left, forecast_days, wagon_number, operation_road '
            'FROM tracking WHERE container_number = %s',
            (num,)
        )
        row = cur.fetchone()
        if row:
            found_rows.append(row)
            cur.execute(
                'INSERT INTO stats(container_number,user_id,username) VALUES(%s,%s,%s)',
                (num, update.effective_user.id, update.effective_user.username)
            )
            conn.commit()
        else:
            not_found.append(num)
    conn.close()

    # Несколько результатов -> Excel
    if len(found_rows) > 1:
        df = pd.DataFrame(found_rows, columns=[
            'Номер контейнера','Станция отправления','Станция назначения',
            'Текущая станция','Операция','Дата операции','Накладная',
            'Осталось км','Прогноз (дн)','Номер вагона','Дорога'
        ])
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Дислокация')
                ws = writer.sheets['Дислокация']
                # Заливка шапки
                fill = PatternFill(fill_type='solid', start_color='87CEEB', end_color='87CEEB')
                for cell in ws[1]: cell.fill = fill
                # Автоматическая ширина
                for col in ws.columns:
                    max_len = max(len(str(cell.value)) for cell in col)
                    ws.column_dimensions[col[0].column_letter].width = max_len + 2
            # Имя файла по времени Владивостока
            vtime = datetime.utcnow() + timedelta(hours=10)
            fname = f'Dislocation_{vtime:%H-%M}.xlsx'
            await update.message.reply_document(open(tmp.name,'rb'), filename=fname)
        if not_found:
            await update.message.reply_text('❌ Не найдены: ' + ', '.join(not_found))
        return

    # Один результат -> текст
    if found_rows:
        row = found_rows[0]
        wagon = 'полувагон' if row[9].startswith('6') else 'платформа'
        text = (
            f'🚛 Контейнер {row[0]} в вагоне {row[9]} ({wagon})\n'
            f'📍 {row[3]} ({row[10]})\n'
            f'🏗 {row[4]} — {row[5]}\n'
            f'Откуда: {row[1]}, Куда: {row[2]}\n'
            f'Накладная: {row[6]}, km left: {row[7]}, прогноз: {row[8]} дн'
        )
        await update.message.reply_text(text)
    else:
        await update.message.reply_text('Ничего не найдено по введённым номерам.')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text('⛔ Доступ запрещён.')
    conn = get_pg_connection(); cur = conn.cursor()
    cur.execute("SELECT user_id, username, COUNT(*) FROM stats GROUP BY 1,2 ORDER BY 3 DESC")
    rows = cur.fetchall(); conn.close()
    if not rows: return await update.message.reply_text('Нет статистики.')
    msg = '📊 Stats:\n' + ''.join(f'{u} ({n}): {cnt}\n' for u,n,cnt in rows)
    await update.message.reply_text(msg)

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text('⛔ Доступ запрещён.')
    conn = get_pg_connection()
    df = pd.read_sql('SELECT * FROM stats', conn); conn.close()
    if df.empty: return await update.message.reply_text('Нет данных.')
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        df.to_excel(tmp.name, index=False)
        await update.message.reply_document(open(tmp.name,'rb'))

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text('⛔ Доступ запрещён.')
    if not context.args:
        return await update.message.reply_text('⚠️ Укажи текст после /broadcast')
    text = ' '.join(context.args)
    await context.bot.send_message(ADMIN_CHAT_ID, f'🔍 Preview:\n{text}')
    context.bot_data['pending'] = text

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text('⛔ Доступ запрещён.')
    text = context.bot_data.get('pending')
    if not text: return await update.message.reply_text('❌ Нет сообщения.')
    conn = get_pg_connection(); cur = conn.cursor()
    cur.execute('SELECT DISTINCT user_id FROM stats'); ids = [r[0] for r in cur.fetchall()]; conn.close()
    ok,fail=0,0
    for uid in ids:
        try: await context.bot.send_message(uid, text); ok+=1
        except: fail+=1
    await update.message.reply_text(f'📤 Sent: ✅{ok} ❌{fail}')
    context.bot_data.pop('pending', None)

async def set_bot_commands(application: Application):
    public = [BotCommand('start','Начать')]
    await application.bot.set_my_commands(public, scope=BotCommandScopeDefault())
    admin = [
        BotCommand('stats','Статистика'),
        BotCommand('exportstats','Export XLSX'),
        BotCommand('broadcast','Preview broadcast'),
        BotCommand('broadcast_confirm','Confirm broadcast')
    ]
    await application.bot.set_my_commands(admin, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))

def main():
    ensure_database_exists()
    start_mail_checking()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('exportstats', exportstats))
    app.add_handler(CommandHandler('broadcast', broadcast))
    app.add_handler(CommandHandler('broadcast_confirm', broadcast_confirm))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.post_init = set_bot_commands
    logger.info('Bot started')
    app.run_webhook(
        listen='0.0.0.0',
        port=int(os.getenv('PORT',10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
