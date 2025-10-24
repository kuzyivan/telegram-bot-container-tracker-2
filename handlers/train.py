# handlers/train.py

from __future__ import annotations
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

from config import ADMIN_CHAT_ID
from logger import get_logger
import re

# 1. ИЗМЕНЕННЫЕ ИМПОРТЫ ЗАПРОСОВ
from queries.train_queries import (
    get_train_client_summary_by_code, 
    get_first_container_in_train,
    get_all_train_codes
) 
from queries.containers import get_latest_tracking_data
from utils.railway_utils import get_railway_abbreviation

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


# --- Бизнес-логика формирования отчёта (ОБНОВЛЕНА) ---
async def _respond_train_report(message, train_no: str):
    logger.info("[/train] train_no(normalized)=%s", train_no)
    
    # 1. Получаем сводку по клиентам
    summary_rows_dict = await get_train_client_summary_by_code(train_no)

    # 2. Получаем последнюю дислокацию по одному из контейнеров
    latest = None
    example_ctn = await get_first_container_in_train(train_no)
    
    if example_ctn:
        # get_latest_tracking_data возвращает Sequence[Tracking] (список)
        latest_tracking_list = await get_latest_tracking_data(example_ctn)
        if latest_tracking_list:
            latest = latest_tracking_list[0] # Берем самую свежую запись
    
    logger.debug("[/train] latest_status=%s", latest)

    # 3. Формирование текста отчета
    lines = [f"🚆 Поезд: *{train_no}*", "───"]

    if summary_rows_dict:
        lines.append("📦 *Сводка по клиентам:*")
        for client, cnt in summary_rows_dict.items():
            lines.append(f"• {client or 'Без клиента'} — *{cnt}*")
    else:
        lines.append("❌ Контейнеры для этого поезда в базе *TerminalContainer* не найдены.")

    if latest:
        # В этом блоке latest - это объект Tracking (из списка)
        lines += ["───", "*Последняя дислокация поезда (по одному из контейнеров):*", f"Контейнер: `{latest.container_number}`"]
        
        # ❗️ НОВОЕ: ДОБАВЛЯЕМ СТАНЦИЮ НАЗНАЧЕНИЯ
        lines.append(f"Станция назначения: `{latest.to_station or 'н/д'}`")
        
        if latest.current_station: 
            # Используем get_railway_abbreviation для форматирования дороги
            railway_abbr = get_railway_abbreviation(latest.operation_road) 
            lines.append(f"Дислокация: ст. *{latest.current_station}* (Дорога: `{railway_abbr}`)")
        
        if latest.operation: 
            lines.append(f"Операция: *{latest.operation}*")
        
        if latest.operation_date: 
            lines.append(f"Дата/время: `{latest.operation_date}`")

    elif summary_rows_dict:
        lines.append("\n⚠️ Дислокация поезда (Tracking) не найдена.")


    try:
        await message.reply_text("\n".join(lines), parse_mode='Markdown')
        logger.info("[/train] reply sent for train=%s", train_no)
    except Exception as e:
        logger.exception("Ошибка в /train для train=%s: %s", train_no, e)
        try:
            await message.reply_text("Не удалось получить данные по поезду.")
        except Exception:
            pass
            
    return ConversationHandler.END


# --- НОВЫЕ ХЕНДЛЕРЫ: Список поездов и обработка выбора ---

async def show_train_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список поездов в виде Inline-кнопок."""
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END
        
    train_codes = await get_all_train_codes()
    
    if not train_codes:
        text = "⚠️ В базе *TerminalContainer* не найдено номеров поездов."
        await update.effective_message.reply_text(text, parse_mode='Markdown')
        return ConversationHandler.END

    text = "🚆 *Выберите поезд для получения дислокации:*"
    keyboard = []
    
    # Создаем кнопки: по 3 в ряд (для удобства)
    row = []
    for code in train_codes:
        # data будет содержать префикс 'train_code_' и сам код поезда
        row.append(InlineKeyboardButton(code, callback_data=f"train_code_{code}"))
        if len(row) == 3: # По 3 кнопки в ряд
            keyboard.append(row)
            row = []
    if row: # Добавляем оставшиеся
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправка/редактирование сообщения
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query and update.callback_query.message:
        # Редактируем сообщение, которое могло быть "Загружаю список поездов..."
        await update.callback_query.message.edit_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown'
        )
        
    return ConversationHandler.END

async def handle_train_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие на кнопку с номером поезда."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("train_code_") or not query.message:
        return
        
    await query.answer("⏳ Собираю отчет...")
    train_no = query.data.split("_")[-1]
    
    # Редактируем сообщение, чтобы убрать кнопки
    await query.message.edit_text(f"⏳ Готовлю отчет по поезду *{train_no}*...", parse_mode='Markdown')
    
    # Вызываем основную логику отчета (используем query.message)
    return await _respond_train_report(query.message, train_no)


# --- Точка входа /train (ИЗМЕНЕНА) ---
async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает команду /train.
    Если есть аргументы - запрашивает отчет.
    Если нет аргументов - показывает список поездов.
    """
    user = update.effective_user
    logger.info(
        "[/train] received from id=%s username=%s args=%s",
        getattr(user, "id", None),
        getattr(user, "username", None),
        context.args,
    )

    if not user or user.id != ADMIN_CHAT_ID:
        logger.warning("[/train] access denied for id=%s", getattr(user, "id", None))
        return ConversationHandler.END

    args = context.args or []
    if args:
        raw = " ".join(args)
        train_no = normalize_train_no(raw) or raw.strip()
        # Если есть аргументы - сразу генерируем отчет
        return await _respond_train_report(update.message, train_no)

    # Если аргументов нет - показываем список поездов
    return await show_train_list(update, context)


async def train_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод номера поезда после запроса."""
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID or not update.message or not update.message.text:
        return ConversationHandler.END

    train_no_raw = update.message.text.strip()
    train_no = normalize_train_no(train_no_raw) or train_no_raw

    await update.message.reply_text(f"⏳ Готовлю отчет по поезду *{train_no}*...", parse_mode='Markdown')
    
    return await _respond_train_report(update.message, train_no)


# --- Функция регистрации хендлеров (ДОПОЛНЕНА) ---

def setup_handlers(app):
    """
    Регистрирует хендлеры для работы с поездами.
    """
    
    # Регистрация хендлера для CallbackQuery
    app.add_handler(
        CallbackQueryHandler(
            handle_train_code_callback, 
            pattern="^train_code_"
        )
    )
    
    # ConversationHandler для ручного ввода номера поезда
    conv = ConversationHandler(
        entry_points=[CommandHandler("train", train_cmd)],
        states={
            ASK_TRAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, train_ask_handler)], 
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
    
    logger.info("✅ handlers.train.setup_handlers: /train (меню/conversation/callback) зарегистрирован")