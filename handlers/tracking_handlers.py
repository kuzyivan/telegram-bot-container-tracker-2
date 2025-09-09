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
from handlers.menu_handlers import reply_keyboard_handler

logger = get_logger(__name__)
GET_CONTAINERS, GET_TIME, GET_EMAILS, GET_NAME, CONFIRM = range(5)
EMAIL_SELECT_PREFIX = "email_select_"

async def create_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user: return ConversationHandler.END
    await query.answer()
    if context.user_data is None: context.user_data = {}
    else: context.user_data.clear()
    logger.info(f"Шаг 1 (Начало): Пользователь {query.from_user.id} начал создание новой подписки.")
    await query.edit_message_text("Шаг 1/4: Введите номера контейнеров для новой подписки (через пробел, запятую или с новой строки).\n\nДля отмены введите /cancel.")
    return GET_CONTAINERS

async def get_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or context.user_data is None or not update.effective_user: return ConversationHandler.END
    containers = [c.strip().upper() for c in re.split(r'[\s,]+', update.message.text) if c.strip()]
    if not containers:
        await update.message.reply_text("Список контейнеров пуст. Пожалуйста, повторите ввод или введите /cancel.")
        return GET_CONTAINERS
    context.user_data['containers'] = containers
    logger.info(f"Шаг 2 (Контейнеры): Пользователь {update.effective_user.id} ввел контейнеры: {containers}")
    keyboard = [[InlineKeyboardButton("🕘 09:00", callback_data="time_09:00")], [InlineKeyboardButton("🕓 16:00", callback_data="time_16:00")]]
    await update.message.reply_text("Шаг 2/4: Отлично! Теперь выберите время для ежедневного отчета:", reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user: return ConversationHandler.END
    await query.answer()
    time_str = query.data.split("_")[1]
    hour, minute = map(int, time_str.split(':'))
    context.user_data['notify_time'] = datetime.time(hour=hour, minute=minute)
    logger.info(f"Шаг 3 (Время): Пользователь {query.from_user.id} выбрал время {time_str}.")
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

async def get_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user: return ConversationHandler.END
    await query.answer()
    if query.data == "emails_done":
        logger.info(f"Шаг 4 (Email Готово): Пользователь {query.from_user.id} завершил выбор email. Выбранные ID: {context.user_data.get('selected_emails')}")
        await query.edit_message_text("Шаг 4/4: Теперь придумайте название для этой подписки (например, 'Контейнеры для клиента А').")
        return GET_NAME
    email_id = int(query.data.replace(EMAIL_SELECT_PREFIX, ""))
    selected_emails = context.user_data.get('selected_emails', set())
    if email_id in selected_emails: selected_emails.remove(email_id)
    else: selected_emails.add(email_id)
    context.user_data['selected_emails'] = selected_emails
    logger.info(f"Шаг 3.1 (Выбор Email): Пользователь {query.from_user.id} изменил выбор. Текущие ID: {selected_emails}")
    user_emails = await get_user_emails(query.from_user.id)
    keyboard = []
    if user_emails:
        for email in user_emails:
            is_selected = email.id in selected_emails
            button_text = f"{'✅' if is_selected else '🔲'} {email.email}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"{EMAIL_SELECT_PREFIX}{email.id}")])
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="emails_done")])
    await query.edit_message_text("Шаг 3/4: Выберите email-адреса для отправки отчета. Нажмите 'Готово', когда закончите.", reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_EMAILS

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or context.user_data is None or not update.effective_user: return ConversationHandler.END
    subscription_name = update.message.text.strip()
    context.user_data['name'] = subscription_name
    logger.info(f"Шаг 5 (Имя): Пользователь {update.effective_user.id} ввел имя подписки: '{subscription_name}'")
    ud = context.user_data
    containers_str = ", ".join([str(c) for c in ud.get('containers', [])])
    text = (f"🔍 *Проверьте и подтвердите*\n\nНазвание: *{ud.get('name', 'Без названия')}*\nКонтейнеры: `{containers_str}`\nВремя отчета: {ud.get('notify_time', datetime.time(9,0)).strftime('%H:%M')}\n")
    email_ids = list(ud.get('selected_emails', []))
    if email_ids:
        user_emails = await get_user_emails(update.effective_user.id)
        selected_email_texts = [e.email for e in user_emails if e.id in email_ids]
        text += f"Email: `{', '.join(selected_email_texts)}`"
    else: text += "Email: _Только в Telegram_"
    keyboard = [[InlineKeyboardButton("🚀 Создать", callback_data="confirm_create"), InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRM

async def confirm_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or context.user_data is None or not query.from_user: return ConversationHandler.END
    if query.data == "cancel_create":
        logger.info(f"Шаг 6 (Отмена): Пользователь {query.from_user.id} отменил создание на финальном шаге.")
        await query.edit_message_text("Создание подписки отменено.")
        context.user_data.clear()
        return ConversationHandler.END
    ud = context.user_data
    logger.info(f"Шаг 6 (Подтверждение): Пользователь {query.from_user.id} подтвердил создание подписки '{ud.get('name')}'.")
    await create_subscription(user_id=query.from_user.id, name=ud.get('name', 'Новая подписка'), containers=ud.get('containers', []), notify_time=ud.get('notify_time', datetime.time(9,0)), email_ids=list(ud.get('selected_emails', [])))
    await query.edit_message_text(f"✅ Новая подписка '{ud.get('name', '')}' успешно создана!")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return ConversationHandler.END
    user_id = update.effective_user.id if update.effective_user else "N/A"
    logger.info(f"Диалог создания подписки отменен командой /cancel пользователем {user_id}.")
    await update.message.reply_text("Действие отменено.")
    if context.user_data: context.user_data.clear()
    return ConversationHandler.END

async def cancel_and_reroute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return ConversationHandler.END
    user_id = update.effective_user.id if update.effective_user else "N/A"
    logger.info(f"Диалог создания подписки отменен нажатием кнопки меню пользователем {user_id}.")
    await update.message.reply_text("Действие отменено. Выполняю команду из меню...")
    if context.user_data: context.user_data.clear()
    await reply_keyboard_handler(update, context)
    return ConversationHandler.END

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
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            MessageHandler(filters.Regex("^(📦 Дислокация|📂 Мои подписки)$"), cancel_and_reroute)
        ],
    )