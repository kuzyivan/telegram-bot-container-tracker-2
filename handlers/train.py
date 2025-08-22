# handlers/train.py
from __future__ import annotations
from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.train_queries import get_train_summary, get_train_latest_status
import re

logger = get_logger(__name__)

# --- Состояния диалога ---
ASK_TRAIN = range(1)

# Нормализация: "к25-076", "K25 076", "к 25–076" -> "К25-076"
_train_re = re.compile(r"^[kк]\s*(\d{2})\s*[-–— ]?\s*(\d{3})$", re.IGNORECASE)

def normalize_train_no(text: str) -> str | None:
    if not text:
        return None
    s = text.strip()
    m = _train_re.match(s)
    if not m:
        return None
    return f"К{m.group(1)}-{m.group(2)}"

# --- Точка входа /train ---
async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(
        "[/train] received from id=%s username=%s args=%s",
        getattr(user, "id", None),
        getattr(user, "username", None),
        context.args,
    )

    # Только админ
    if not user or user.id != ADMIN_CHAT_ID:
        logger.warning("[/train] access denied for id=%s", getattr(user, "id", None))
        return

    args = context.args or []
    # Если номер пришёл аргументом — сразу отчёт
    if args:
        raw = " ".join(args)
        train_no = normalize_train_no(raw) or raw.strip()
        return await _respond_train_report(update, train_no)

    # Иначе просим ввести номер отдельным сообщением
    await update.message.reply_text(
        "Введите номер поезда (пример: К25-076). Регистр не важен: можно к25-076 или k25 076."
    )
    return ASK_TRAIN

# --- Обработка ответа с номером поезда ---
async def train_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END

    raw = (update.message.text or "").strip()
    train_no = normalize_train_no(raw)
    if not train_no:
        await update.message.reply_text(
            "Неверный формат. Пример: К25-076. Попробуйте ещё раз."
        )
        return ASK_TRAIN

    return await _respond_train_report(update, train_no)

# --- Бизнес-логика формирования отчёта ---
async def _respond_train_report(update: Update, train_no: str):
    logger.info("[/train] train_no(normalized)=%s", train_no)
    try:
        summary_rows = await get_train_summary(train_no)
        if not summary_rows:
            await update.message.reply_html(f"Поезд «<b>{train_no}</b>» не найден в базе.")
            logger.info("[/train] no rows for train=%s", train_no)
            return ConversationHandler.END

        latest = await get_train_latest_status(train_no)
        logger.debug("[/train] latest_status=%s", latest)

        lines = [
            f"🚆 Поезд: <b>{train_no}</b>",
            "───",
            "<b>Сводка по клиентам (кол-во контейнеров):</b>",
        ]
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
                wagon_str = str(wagon)
                if wagon_str.endswith(".0"):
                    wagon_str = wagon_str[:-2]
                lines.append(f"Номер вагона: {wagon_str}")
            if road:
                lines.append(f"Дорога: {road}")

        await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)
        logger.info("[/train] reply sent for train=%s", train_no)
    except Exception as e:
        logger.exception("Ошибка в /train для train=%s: %s", train_no, e)
        try:
            await update.message.reply_text(
                "Не удалось получить данные по поезду. Подробности в логах."
            )
        except Exception:
            pass
    return ConversationHandler.END

# --- Регистрация хендлеров ---
def setup_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler("train", train_cmd)],
        states={
            ASK_TRAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, train_ask_handler)],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
    logger.info("✅ handlers.train.setup_handlers: /train (conversation) зарегистрирован")