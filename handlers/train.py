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
# 1. ИЗМЕНЕННЫЕ ИМПОРТЫ
from queries.train_queries import get_train_client_summary_by_code, get_first_container_in_train
from queries.containers import get_latest_tracking_data
import re

logger = get_logger(__name__)

# --- Состояния диалога ---
ASK_TRAIN = range(1)

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

    # ИСПРАВЛЕНИЕ 1: Добавляем проверку, что update.message существует
    if not update.message:
        logger.warning("[/train] train_cmd called without a message.")
        return

    if not user or user.id != ADMIN_CHAT_ID:
        logger.warning("[/train] access denied for id=%s", getattr(user, "id", None))
        return

    args = context.args or []
    if args:
        raw = " ".join(args)
        train_no = normalize_train_no(raw) or raw.strip()
        # ИСПРАВЛЕНИЕ 2: Передаем 'update.message' вместо 'update' для ясности
        return await _respond_train_report(update.message, train_no)

    await update.message.reply_text(
        "Введите номер поезда (пример: К25-076)."
    )
    return ASK_TRAIN


# --- Обработка ответа с номером поезда ---
async def train_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ 3: Добавляем проверку, что update.message существует
    if not update.message:
        logger.warning("[/train] train_ask_handler called without a message.")
        return ConversationHandler.END

    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END

    # ИСПРАВЛЕНИЕ 4: Добавляем проверку, что update.message.text существует
    raw = (update.message.text or "").strip()
    train_no = normalize_train_no(raw)
    if not train_no:
        await update.message.reply_text(
            "Неверный формат. Пример: К25-076. Попробуйте ещё раз."
        )
        return ASK_TRAIN

    return await _respond_train_report(update.message, train_no)


# --- Бизнес-логика формирования отчёта ---
# ИСПРАВЛЕНИЕ 5: Принимаем объект Message, а не Update, так как работаем только с ним
async def _respond_train_report(message, train_no: str):
    logger.info("[/train] train_no(normalized)=%s", train_no)
    try:
        # 2. ИЗМЕНЕННАЯ ЛОГИКА (часть 1)
        # 1. Используем новую функцию для сводки
        summary_rows_dict = await get_train_client_summary_by_code(train_no)
        if not summary_rows_dict:
            await message.reply_html(f"Поезд «<b>{train_no}</b>» не найден в базе.")
            logger.info("[/train] no rows for train=%s", train_no)
            return ConversationHandler.END

        # 2. Используем новую логику для получения дислокации
        latest = None
        example_ctn = await get_first_container_in_train(train_no)
        if example_ctn:
            # Находим последнюю запись дислокации для этого контейнера
            latest_tracking_list = await get_latest_tracking_data(example_ctn)
            if latest_tracking_list:
                latest = latest_tracking_list[0] # Берем самую свежую запись
        
        logger.debug("[/train] latest_status=%s", latest)

        # 3. ИЗМЕНЕННАЯ ЛОГИКА (часть 2)
        lines = [f"🚆 Поезд: <b>{train_no}</b>", "───", "<b>Сводка по клиентам:</b>"]
        # 1. Итерируемся по словарю .items()
        for client, cnt in summary_rows_dict.items():
            lines.append(f"• {client or 'Без клиента'} — <b>{cnt}</b>")

        if latest:
            # 2. Обращаемся к атрибутам объекта latest, а не к индексам
            lines += ["───", "<b>Дислокация поезда (по одному из контейнеров):</b>", f"Контейнер: <code>{latest.container_number}</code>"]
            if latest.operation: lines.append(f"Операция: {latest.operation}")
            if latest.current_station: lines.append(f"Станция: {latest.current_station}")
            if latest.operation_date: lines.append(f"Дата/время: {latest.operation_date}")
            if latest.wagon_number: lines.append(f"Номер вагона: {str(latest.wagon_number).removesuffix('.0')}")
            if latest.operation_road: lines.append(f"Дорога: {latest.operation_road}")

        await message.reply_html("\n".join(lines), disable_web_page_preview=True)
        logger.info("[/train] reply sent for train=%s", train_no)
    except Exception as e:
        logger.exception("Ошибка в /train для train=%s: %s", train_no, e)
        try:
            await message.reply_text("Не удалось получить данные по поезду.")
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