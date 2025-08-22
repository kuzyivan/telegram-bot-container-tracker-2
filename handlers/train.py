from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.train_queries import get_train_summary, get_train_latest_status

logger = get_logger(__name__)

async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("[/train] received from id=%s username=%s args=%s",
                getattr(user, "id", None), getattr(user, "username", None), context.args)

    # Только админ
    if not user or user.id != ADMIN_CHAT_ID:
        logger.warning("[/train] access denied for id=%s", getattr(user, "id", None))
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("Укажи номер поезда: /train К25-073")
        return

    train_no = " ".join(args).strip()
    logger.info("[/train] train_no=%s", train_no)

    try:
        summary_rows = await get_train_summary(train_no)
        if not summary_rows:
            await update.message.reply_html(f"Поезд «<b>{train_no}</b>» не найден в базе.")
            logger.info("[/train] no rows for train=%s", train_no)
            return

        latest = await get_train_latest_status(train_no)
        logger.debug("[/train] latest_status=%s", latest)

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
        logger.info("[/train] reply sent for train=%s", train_no)

    except Exception as e:
        logger.exception("Ошибка в /train для train=%s: %s", train_no, e)
        # максимально безопасный ответ, чтобы не молчать
        try:
            await update.message.reply_text("Не удалось получить данные по поезду. Подробности в логах.")
        except Exception:
            pass


def setup_handlers(app):
    app.add_handler(CommandHandler("train", train_cmd))
    logger.info("✅ handlers.train.setup_handlers: /train зарегистрирован")