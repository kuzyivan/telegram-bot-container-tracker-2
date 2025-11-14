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

# 1. ИЗМЕНЕННЫЕ ИМПОРТЫ
from queries.train_queries import (
    get_all_train_codes
) 
# --- ✅ НОВЫЙ ИМПОРТ ФУНКЦИИ ОТЧЕТА ---
from handlers.admin.uploads import _build_and_send_report

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


# --- 2. ❌ СТАРАЯ ФУНКЦИЯ _respond_train_report УДАЛЕНА ---


# --- НОВЫЕ ХЕНДЛЕРЫ: Список поездов и обработка выбора ---

async def show_train_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список поездов в виде Inline-кнопок."""
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END
    
    # --- ✅ ИЗМЕНЕНИЕ: Используем новую таблицу Train ---
    # (Мы все еще берем список из TerminalContainer, т.к. там все поезда)
    train_codes = await get_all_train_codes()
    
    if not train_codes:
        text = "⚠️ В базе *TerminalContainer* не найдено номеров поездов."
        await update.effective_message.reply_text(text, parse_mode='Markdown')
        return ConversationHandler.END

    text = "🚆 *Выберите поезд для получения отчета:*"
    keyboard = []
    
    row = []
    for code in train_codes:
        row.append(InlineKeyboardButton(code, callback_data=f"train_code_{code}"))
        if len(row) == 3: # По 3 кнопки в ряд
            keyboard.append(row)
            row = []
    if row: # Добавляем оставшиеся
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query and update.callback_query.message:
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
    
    await query.message.edit_text(f"⏳ Готовлю отчет по поезду *{train_no}*...", parse_mode='Markdown')
    
    # --- 3. ✅ ВЫЗЫВАЕМ НОВУЮ ФУНКЦИЮ ОТЧЕТА ---
    await _build_and_send_report(query.message, train_no)
    return ConversationHandler.END


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
    
    if not update.message:
        return ConversationHandler.END

    args = context.args or []
    if args:
        raw = " ".join(args)
        train_no = normalize_train_no(raw) or raw.strip()
        
        # --- 3. ✅ ВЫЗЫВАЕМ НОВУЮ ФУНКЦИЮ ОТЧЕТА ---
        await update.message.reply_text(f"⏳ Готовлю отчет по поезду *{train_no}*...", parse_mode='Markdown')
        await _build_and_send_report(update.message, train_no)
        return ConversationHandler.END

    # Если аргументов нет - показываем список поездов
    return await show_train_list(update, context)


async def train_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод номера поезда после запроса."""
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID or not update.message or not update.message.text:
        return ConversationHandler.END

    train_no_raw = update.message.text.strip()
    train_no = normalize_train_no(train_no_raw) or train_no_raw

    # --- 3. ✅ ВЫЗЫВАЕМ НОВУЮ ФУНКЦИЮ ОТЧЕТА ---
    await update.message.reply_text(f"⏳ Готовлю отчет по поезду *{train_no}*...", parse_mode='Markdown')
    await _build_and_send_report(update.message, train_no)
    return ConversationHandler.END


# --- Функция регистрации хендлеров (ОБНОВЛЕНА) ---

def setup_handlers(app):
    """
    Регистрирует хендлеры для работы с поездами.
    """
    
    # Отдельный обработчик для нажатия кнопок (вне диалога)
    app.add_handler(
        CallbackQueryHandler(
            handle_train_code_callback, 
            pattern="^train_code_"
        )
    )
    
    # ConversationHandler нужен только для случая, если /train вызван без аргументов,
    # а затем пользователь вводит текст.
    # (Хотя текущая логика train_cmd сразу показывает кнопки, 
    # этот ConversationHandler остается для совместимости)
    conv = ConversationHandler(
        entry_points=[CommandHandler("train", train_cmd)],
        states={
            ASK_TRAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, train_ask_handler)], 
        },
        fallbacks=[],
        allow_reentry=True,
        name="train_conversation",
    )
    app.add_handler(conv)
    
    logger.info("✅ handlers.train.setup_handlers: /train (меню/conversation/callback) зарегистрирован")