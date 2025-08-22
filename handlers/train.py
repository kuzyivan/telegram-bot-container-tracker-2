from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.train_queries import get_train_summary, get_train_latest_status

logger = get_logger(__name__)

async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("Укажи номер поезда: /train К25-073")
        return

    train_no = " ".join(args).strip()

    try:
        summary_rows = await get_train_summary(train_no)
        if not summary_rows:
            await update.message.reply_html(f"Поезд «<b>{train_no}</b>» не найден в базе.")
            return

        latest = await get_train_latest_status(train_no)

        # --- Формируем текст ---
        lines = [f"🚆 Поезд: <b>{train_no}</b>", "───", "<b>Сводка по клиентам (кол-во контейнеров):</b>"]
        for client, cnt in summary_rows:
            lines.append(f"• {client or 'Без клиента'} — <b>{cnt}</b>")

        if latest:
            ctn, operation, station, op_date, wagon, road = latest
            lines += [
                "───",
                "<b>Дислокация поезда (по одному из контейнеров):</b>",
                f"Контейнер: <code>{ctn}</code>",
                f"Операция: {operation or '—'}",
                f"Станция: {station or '—'}",
                f"Дата/время: {op_date or '—'}",
            ]
            if wagon:
                lines.append(f"Номер вагона: {wagon}")
            if road:
                lines.append(f"Дорога: {road}")

        await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)

    except Exception as e:
        logger.exception("Ошибка /train %s", e)
        await update.message.reply_text("Не удалось получить данные по поезду. Подробности в логах.")

def setup_handlers(app):
    app.add_handler(CommandHandler("train", train_cmd))