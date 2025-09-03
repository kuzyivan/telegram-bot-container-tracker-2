# handlers/tracking_handlers.py
import re
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters,
    CommandHandler
)
from logger import get_logger
from queries.user_queries import get_user_emails
from queries.subscription_queries import create_subscription

logger = get_logger(__name__)

# Определяем состояния для диалога
GET_CONTAINERS, GET_TIME, GET_EMAILS, GET_NAME, CONFIRM = range(5)
# Константа для callback_data
EMAIL_SELECT_PREFIX = "email_select_"

# --- Шаг 1: Начало диалога ---
async def create_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    
    await query.answer()
    
    # ИСПРАВЛЕНИЕ: Гарантируем, что user_data существует и пуст
    if context.user_data is None:
        context.user_data = {}
    else:
        context.user_data.clear()

    await query.edit_message_text(
        "Шаг 1/4: Введите номера контейнеров для новой подписки (через пробел, запятую или с новой строки).\n\nДля отмены введите /cancel."
    )
    return GET_CONTAINERS

# --- Шаг 2: Получение номеров контейнеров ---
async def get_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИСПРАВЛЕНИЕ: Проверяем, что user_data не None, а не то, что он не пуст
    if not update.message or not update.message.text or context.user_data is None:
        return ConversationHandler.END

    containers = [c.strip().upper() for c in re.split(r'[\s,]+', update.message.text) if c.strip()]
    if not containers:
        await update.message.reply_text("Список контейнеров пуст. Пожалуйста, повторите ввод или введите /cancel.")
        return GET_CONTAINERS

    context.user_data['containers'] = containers
    
    keyboard = [
        [InlineKeyboardButton("🕘 09:00", callback_data="time_09:00")],
        [InlineKeyboardButton("🕓 16:00", callback_data="time_16:00")]
    ]
    await update.message.reply_text(
        "Шаг 2/4: Отлично! Теперь выберите время для ежедневного отчета:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GET_TIME

# --- Шаг 3: Получение времени и запрос email ---
async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user:
        return ConversationHandler.END

    await query.answer()
    
    time_str = query.data.split("_")[1]
    hour, minute = map(int, time_str.split(':'))
    context.user_data['notify_time'] = datetime.time(hour=hour, minute=minute)

    user_emails = await get_user_emails(query.from_user.id)
    context.user_data['selected_emails'] = set()

    text = "Шаг 3/4: Выберите email-адреса для отправки отчета (можно несколько). Нажмите 'Готово', когда закончите."
    keyboard = []
    if user_emails:
        for email in user_emails:
            keyboard.append([InlineKeyboardButton(f"🔲 {email.email}", callback_data=f"{EMAIL_SELECT_PREFIX}{email.id}")])
    
    keyboard.append([InlineKeyboardButton("✅ Готово (только в Telegram)", callback_data="emails_done")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_EMAILS

# --- Шаг 4: Выбор email-адресов ---
async def get_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user:
        return ConversationHandler.END

    await query.answer()

    if query.data == "emails_done":
        await query.edit_message_text("Шаг 4/4: Теперь придумайте название для этой подписки (например, 'Контейнеры для клиента А').")
        return GET_NAME

    email_id = int(query.data.replace(EMAIL_SELECT_PREFIX, ""))
    selected_emails = context.user_data.get('selected_emails', set())

    if email_id in selected_emails:
        selected_emails.remove(email_id)
    else:
        selected_emails.add(email_id)
    context.user_data['selected_emails'] = selected_emails

    user_emails = await get_user_emails(query.from_user.id)
    keyboard = []
    if user_emails:
        for email in user_emails:
            is_selected = email.id in selected_emails
            button_text = f"{'✅' if is_selected else '🔲'} {email.email}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"{EMAIL_SELECT_PREFIX}{email.id}")])

    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="emails_done")])
    await query.edit_message_text(
        "Шаг 3/4: Выберите email-адреса для отправки отчета. Нажмите 'Готово', когда закончите.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GET_EMAILS

# --- Шаг 5: Получение названия и подтверждение ---
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or context.user_data is None or not update.effective_user:
        return ConversationHandler.END
        
    context.user_data['name'] = update.message.text.strip()
    
    ud = context.user_data
    containers_str = ", ".join([str(c) for c in ud.get('containers', [])])
    
    text = (
        f"🔍 *Проверьте и подтвердите*\n\n"
        f"Название: *{ud.get('name', 'Без названия')}*\n"
        f"Контейнеры: `{containers_str}`\n"
        f"Время отчета: {ud.get('notify_time', datetime.time(9,0)).strftime('%H:%M')}\n"
    )
    
    email_ids = list(ud.get('selected_emails', []))
    if email_ids:
        user_emails = await get_user_emails(update.effective_user.id)
        selected_email_texts = [e.email for e in user_emails if e.id in email_ids]
        text += f"Email: `{', '.join(selected_email_texts)}`"
    else:
        text += "Email: _Только в Telegram_"

    keyboard = [[
        InlineKeyboardButton("🚀 Создать", callback_data="confirm_create"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")
    ]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRM

# --- Шаг 6: Финальное создание ---
async def confirm_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user:
        return ConversationHandler.END

    if query.data == "cancel_create":
        await query.edit_message_text("Создание подписки отменено.")
        context.user_data.clear()
        return ConversationHandler.END

    ud = context.user_data
    await create_subscription(
        user_id=query.from_user.id,
        name=ud.get('name', 'Новая подписка'),
        containers=ud.get('containers', []),
        notify_time=ud.get('notify_time', datetime.time(9,0)),
        email_ids=list(ud.get('selected_emails', []))
    )
    
    await query.edit_message_text(f"✅ Новая подписка '{ud.get('name', '')}' успешно создана!")
    context.user_data.clear()
    return ConversationHandler.END

# --- Отмена диалога ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_to_send = "Действие отменено."
    if update.message:
        await update.message.reply_text(message_to_send)
    elif update.callback_query:
        await update.callback_query.edit_message_text(message_to_send)

    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

# --- Собираем все в один ConversationHandler ---
def tracking_conversation_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(create_subscription_start, pattern="^create_sub_start$")],
        states={
            GET_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_containers)],
            GET_TIME: [CallbackQueryHandler(get_time, pattern="^time_")],
            GET_EMAILS: [CallbackQueryHandler(get_emails, pattern=f"^(emails_done|{EMAIL_SELECT_PREFIX})")],
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CONFIRM: [CallbackQueryHandler(confirm_creation, pattern="^confirm_create|cancel_create$")]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )