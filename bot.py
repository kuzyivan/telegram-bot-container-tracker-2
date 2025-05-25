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

# Настройка логирования
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))


def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    await update.message.reply_text(
        "Привет! Отправь мне номер контейнера для отслеживания."
    )


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка стикеров: вывод их file_id"""
    sticker_id = update.message.sticker.file_id
    await update.message.reply_text(
        f"🆔 ID этого стикера:\n`{sticker_id}`",
        parse_mode='Markdown'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основная логика: поиск в БД и ответ пользователю"""
    text = update.message.text.strip().upper()
    numbers = [t for t in text.split() if t]

    conn = get_pg_connection()
    cur = conn.cursor()

    results = []
    not_found = []
    for num in numbers:
        cur.execute(
            "SELECT * FROM tracking WHERE container_number = %s", (num,)
        )
        row = cur.fetchone()
        if row:
            results.append(row)
            # сохраняем в stats
            cur.execute(
                "INSERT INTO stats(container_number, user_id, username) VALUES(%s, %s, %s)",
                (num, update.effective_user.id, update.effective_user.username)
            )
            conn.commit()
        else:
            not_found.append(num)
    conn.close()

    if not results:
        await update.message.reply_text("Ничего не найдено по введённым номерам.")
        return

    # если несколько — XLSX
    if len(results) > 1:
        df = pd.DataFrame(results, columns=[
            'Номер контейнера','Откуда','Куда','Где','Операция','Когда',
            'Накладная','Км','Прогноз','Вагон','Дорога'
        ])
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            df.to_excel(tmp.name, index=False)
            await update.message.reply_document(open(tmp.name, 'rb'))
        if not_found:
            await update.message.reply_text(
                "❌ Не найдены: " + ", ".join(not_found)
            )
        return

    # одиночный ответ
    row = results[0]
    msg = (
        f"🚛 Контейнер: {row[0]}\n"
        f"📍 {row[3]} — {row[4]} ({row[5]})\n"
        f"Откуда: {row[1]}, Куда: {row[2]}\n"
        f"Накладная: {row[6]}, Осталось км: {row[7]}, Прогноз: {row[8]} дн."
    )
    await update.message.reply_text(msg)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вывод статистики (только админ)"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, username, COUNT(*) AS cnt
        FROM stats GROUP BY user_id, username ORDER BY cnt DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return await update.message.reply_text("Нет статистики.")
    text = "📊 Статистика:\n"
    for u, name, cnt in rows:
        text += f"👤 {name or u}: {cnt}\n"
    await update.message.reply_text(text)


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт статистики в XLSX (только админ)"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    conn = get_pg_connection()
    df = pd.read_sql("SELECT * FROM stats", conn)
    conn.close()
    if df.empty:
        return await update.message.reply_text("Нет данных для экспорта.")
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        df.to_excel(tmp.name, index=False)
        await update.message.reply_document(open(tmp.name, 'rb'))


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Предпросмотр рассылки (админ)"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    if not context.args:
        return await update.message.reply_text(
            "⚠️ Укажи текст после /broadcast"
        )
    text = " ".join(context.args)
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🔍 Предпросмотр:\n\n{text}\n\n/​broadcast_confirm для отправки"
    )
    context.bot_data['pending'] = text


async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и отправка рассылки (админ)"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return await update.message.reply_text("⛔ Доступ запрещён.")
    text = context.bot_data.get('pending')
    if not text:
        return await update.message.reply_text("❌ Нет сообщения для рассылки.")
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM stats")
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    ok, fail = 0, 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
    await update.message.reply_text(
        f"📤 Рассылка завершена: ✅{ok}  ❌{fail}"
    )
    context.bot_data.pop('pending', None)


async def set_bot_commands(application: Application):
    public = [BotCommand('start','Начать')]
    await application.bot.set_my_commands(public, scope=BotCommandScopeDefault())
    admin = [
        BotCommand('stats','Статистика'),
        BotCommand('exportstats','Выгрузка XLSX'),
        BotCommand('broadcast','Предпросмотр рассылки'),
        BotCommand('broadcast_confirm','Подтвердить рассылку')
    ]
    await application.bot.set_my_commands(admin, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))


def keep_alive():
    """Пинг Render, чтобы не засыпал"""
    def ping():
        url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}"
        while True:
            try:
                requests.get(url)
            except:
                pass
            time.sleep(600)
    threading.Thread(target=ping,daemon=True).start()


def main():
    ensure_database_exists()
    start_mail_checking()
    keep_alive()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('exportstats', exportstats))
    app.add_handler(CommandHandler('broadcast', broadcast))
    app.add_handler(CommandHandler('broadcast_confirm', broadcast_confirm))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.post_init = set_bot_commands
    logging.info("Бот запущен")
    app.run_webhook(
        listen='0.0.0.0',
        port=int(os.environ.get('PORT',10000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )


if __name__ == '__main__':
    main()
