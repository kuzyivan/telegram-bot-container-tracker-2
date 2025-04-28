import os
import logging
import pandas as pd
import re
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters,
)
from mail_reader import start_mail_checking
from backup_db import start_backup_scheduler

# Переменные окружения
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/16PZrxpzsfBkF7hGN4OKDx6CRfIqySES4oLL9OoxOV8Q/export?format=csv"
PORT = int(os.environ.get("PORT", 10000))  # Render сам подставит нужный порт
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация приложения Telegram
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для отслеживания контейнеров по железной дороге.\n\n"
        "Просто пришли мне номер контейнера или список контейнеров!"
    )

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Помощь:\n\n"
        "Отправь номер контейнера или список — и я покажу их статус."
    )

# /refresh
async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Данные обновляются автоматически!")

# Обработка контейнеров
async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip().upper()
    container_list = re.split(r'[\s,;:\n\r\.]+', message_text)
    container_list = [c for c in container_list if c]

    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        df.columns = [str(col).strip().replace('\ufeff', '') for col in df.columns]
        df["Дата и время операции"] = pd.to_datetime(df["Дата и время операции"], format="%d.%m.%Y %H:%M:%S", errors='coerce')

        result_df = (
            df[df["Номер контейнера"].isin(container_list)]
            .sort_values("Дата и время операции", ascending=False)
            .drop_duplicates(subset=["Номер контейнера"])
        )

        if result_df.empty:
            await update.message.reply_text("⚠️ Контейнеры не найдены.")
            return

        grouped = result_df.groupby(["Станция отправления", "Станция назначения"])
        reply = "📦 Отчёт по контейнерам:\n"

        for (start_station, end_station), group in grouped:
            reply += f"\n🚆 *Маршрут:* {start_station} → {end_station}\n"
            for _, row in group.iterrows():
                station_name = str(row.get("Станция операции", "Неизвестно")).split("(")[0].strip().upper()
                date_op = row["Дата и время операции"]
                eta_str = "неизвестна"

                if pd.notnull(row.get("Расстояние оставшееся")):
                    try:
                        km = float(row["Расстояние оставшееся"])
                        eta_days = int(round(km / 600))
                        eta_str = f"через {eta_days} дн." if eta_days > 0 else "менее суток"
                    except Exception:
                        pass

                date_op_str = "неизвестна" if pd.isnull(date_op) else date_op.strftime('%Y-%m-%d %H:%M')

                if "выгрузка из вагона" in str(row.get('Операция', '')).lower():
                    reply += (
                        f"🕓 Дата операции: {date_op_str}\n"
                        f"📬 Контейнер прибыл на станцию назначения!\n"
                    )
                else:
                    reply += (
                        f"📦 № Контейнера: `{row['Номер контейнера']}`\n"
                        f"📍 Дислокация: {station_name}\n"
                        f"⚙️ Операция: {row.get('Операция', 'Неизвестно')}\n"
                        f"🕓 Дата операции: {date_op_str}\n"
                        f"📅 Прогноз прибытия: {eta_str}\n"
                    )

        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Ошибка при обработке запроса")
        await update.message.reply_text("⚠️ Ошибка при обработке запроса. Попробуйте позже.")

# Регистрируем команды и обработчики
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("refresh", refresh))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track))

# Запуск
if __name__ == '__main__':
    start_mail_checking()       # Фоновая проверка почты
    start_backup_scheduler()    # Фоновый бэкап базы

    # Асинхронный запуск вебхука
    async def run():
        await telegram_app.start()
        await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        await telegram_app.updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook"
        )

    asyncio.run(run())
