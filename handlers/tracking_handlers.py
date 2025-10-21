# handlers/tracking_handlers.py
import re
from datetime import time
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
from sqlalchemy import select 

from logger import get_logger
from db import SessionLocal
from models import Subscription, UserEmail, SubscriptionEmail 
from queries.subscription_queries import get_user_subscriptions, delete_subscription, get_subscription_details 
from queries.user_queries import get_user_emails 
# ✅ Импортируем НОВУЮ функцию клавиатуры
from utils.keyboards import create_yes_no_inline_keyboard, create_time_keyboard, create_email_keyboard 

logger = get_logger(__name__)

# Состояния диалога
(ASK_NAME, ASK_CONTAINERS, ASK_TIME, ASK_EMAILS, CONFIRM_SAVE) = range(5)
# Ключи для context.user_data
(NAME, CONTAINERS, TIME, EMAILS) = ("sub_name", "sub_containers", "sub_time", "sub_emails")

def normalize_containers(text: str) -> list[str]:
    """Извлекает и нормализует номера контейнеров из текста."""
    found = re.findall(r'[A-Z]{3}U\d{7}', text.upper())
    return sorted(list(set(found)))

async def add_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога создания подписки."""
    if update.effective_user and context.user_data: 
        logger.info(f"Пользователь {update.effective_user.id} начал создание подписки.")
        context.user_data.clear() 
    if update.message:
        await update.message.reply_text("Введите название для новой подписки (например, 'Контейнеры для клиента А'):")
        return ASK_NAME
    return ConversationHandler.END

async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает название, запрашивает номера контейнеров."""
    if not update.message or not update.message.text or not context.user_data: 
        return ConversationHandler.END

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не может быть пустым. Попробуйте снова:")
        return ASK_NAME

    context.user_data[NAME] = name
    if update.effective_user:
        logger.info(f"Пользователь {update.effective_user.id} ввел название подписки: {name}")
    await update.message.reply_text("Отправьте номера контейнеров (можно списком, через запятую или пробел):")
    return ASK_CONTAINERS

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает контейнеры, запрашивает время уведомления."""
    if not update.message or not update.message.text or not context.user_data: 
        return ConversationHandler.END

    containers = normalize_containers(update.message.text)
    if not containers:
        await update.message.reply_text("Не найдено корректных номеров контейнеров (формат XXXU1234567). Попробуйте снова:")
        return ASK_CONTAINERS

    context.user_data[CONTAINERS] = containers
    if update.effective_user:
        logger.info(f"Пользователь {update.effective_user.id} ввел контейнеры: {containers}")

    await update.message.reply_text("Выберите время для ежедневной рассылки:", reply_markup=create_time_keyboard())
    return ASK_TIME

async def ask_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает время (через колбэк), запрашивает email для рассылки."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("time_") or not context.user_data or not update.effective_user: 
        return ConversationHandler.END

    await query.answer()
    time_str = query.data.split("_")[1] 
    try:
        hour, minute = map(int, time_str.split(':'))
        selected_time = time(hour, minute)
        context.user_data[TIME] = selected_time
        logger.info(f"Пользователь {update.effective_user.id} выбрал время: {selected_time}")

        user_emails = await get_user_emails(update.effective_user.id)
        if user_emails:
            context.user_data[EMAILS] = [] 
            if query.message:
                await query.edit_message_text(
                    "Выберите Email для рассылки по этой подписке (можно несколько). "
                    "Если не выбрать ни одного, рассылка будет только в Telegram.",
                    reply_markup=create_email_keyboard(user_emails)
                )
            return ASK_EMAILS
        else:
            context.user_data[EMAILS] = []
            logger.info(f"У пользователя {update.effective_user.id} нет сохраненных email, пропускаем выбор.")
            return await confirm_save(update, context) 

    except ValueError:
        if query.message:
            await query.edit_message_text("Некорректное время. Попробуйте еще раз.")
        return ConversationHandler.END

async def handle_email_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор email (добавление/удаление) или переход к подтверждению."""
    query = update.callback_query
    if not query or not query.data or not context.user_data or not update.effective_user: 
        return ConversationHandler.END
    await query.answer()

    action = query.data
    user_emails = await get_user_emails(update.effective_user.id) 
    selected_emails_ids = set(context.user_data.get(EMAILS, [])) 

    if action.startswith("email_"):
        email_id = int(action.split("_")[1])
        if email_id in selected_emails_ids:
            selected_emails_ids.remove(email_id)
        else:
            selected_emails_ids.add(email_id)
        context.user_data[EMAILS] = list(selected_emails_ids)
        if query.message:
            await query.edit_message_reply_markup(reply_markup=create_email_keyboard(user_emails, selected_emails_ids))
        return ASK_EMAILS 

    elif action == "confirm_emails":
        return await confirm_save(update, context)

    return ASK_EMAILS

async def confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает сводку и спрашивает подтверждение."""
    query = update.callback_query 
    message = query.message if query else update.message 
    if not message or not context.user_data or not update.effective_user: 
        return ConversationHandler.END

    ud = context.user_data
    name = ud.get(NAME)
    containers = ud.get(CONTAINERS, [])
    selected_time = ud.get(TIME)
    selected_email_ids = ud.get(EMAILS, [])

    email_texts = []
    if selected_email_ids:
         user_emails = await get_user_emails(update.effective_user.id)
         email_map = {e.id: e.email for e in user_emails}
         email_texts = [email_map.get(eid, "?") for eid in selected_email_ids]

    summary = [
        f"**Название:** {name}",
        f"**Контейнеры ({len(containers)}):** {', '.join(containers)}",
        f"**Время:** {selected_time.strftime('%H:%M') if selected_time else 'Не задано'}",
        f"**Email:** {', '.join(email_texts) if email_texts else 'Нет'}"
    ]
    text = "Проверьте данные:\n\n" + "\n".join(summary) + "\n\nСохранить?"

    # ✅ Используем НОВУЮ функцию для Inline Да/Нет
    reply_markup = create_yes_no_inline_keyboard("save_sub", "cancel_sub") 

    if query:
         await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif message: 
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    return CONFIRM_SAVE

async def save_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет подписку в базу данных."""
    query = update.callback_query
    if not query or not query.data == "save_sub" or not context.user_data or not update.effective_user: 
        return ConversationHandler.END
    await query.answer()

    ud = context.user_data
    user_id = update.effective_user.id

    sub_name = ud.get(NAME)
    sub_containers = ud.get(CONTAINERS)
    sub_time = ud.get(TIME)

    if not all([sub_name, sub_containers, sub_time]):
         logger.error(f"Недостаточно данных в user_data для сохранения подписки пользователя {user_id}. Данные: {ud}")
         if query.message:
             await query.edit_message_text("❌ Ошибка: Недостаточно данных. Попробуйте начать заново.")
         return ConversationHandler.END

    try:
        async with SessionLocal() as session:
            async with session.begin():
                new_subscription = Subscription(
                    user_telegram_id=user_id,
                    subscription_name=sub_name, 
                    containers=sub_containers,
                    notification_time=sub_time,
                    is_active=True
                )
                session.add(new_subscription)
                await session.flush() 

                selected_email_ids = ud.get(EMAILS, [])
                if selected_email_ids:
                    result = await session.execute( 
                        select(UserEmail).filter(UserEmail.id.in_(selected_email_ids), UserEmail.user_telegram_id == user_id)
                    )
                    emails_to_link = result.scalars().all()
                    for email_obj in emails_to_link:
                         sub_email_link = SubscriptionEmail(subscription_id=new_subscription.id, email_id=email_obj.id)
                         session.add(sub_email_link)
                await session.commit() 

        logger.info(f"Пользователь {user_id} успешно сохранил подписку ID {new_subscription.id}")
        if query.message:
            await query.edit_message_text("✅ Подписка успешно создана!")

    except Exception as e:
        logger.error(f"Ошибка сохранения подписки для пользователя {user_id}: {e}", exc_info=True)
        if query.message:
            await query.edit_message_text("❌ Произошла ошибка при сохранении подписки.")

    if context.user_data: context.user_data.clear()
    return ConversationHandler.END

async def cancel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена создания подписки."""
    if context.user_data:
        context.user_data.clear()

    query = update.callback_query
    if query and query.message:
         await query.answer()
         await query.edit_message_text("Создание подписки отменено.")
    elif update.message:
         await update.message.reply_text("Создание подписки отменено.")

    if update.effective_user:
        logger.info(f"Пользователь {update.effective_user.id} отменил создание подписки.")
    return ConversationHandler.END


def tracking_conversation_handler():
    """Возвращает ConversationHandler для создания подписки."""
    return ConversationHandler(
        entry_points=[CommandHandler("add_subscription", add_subscription_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_containers)],
            ASK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TIME: [CallbackQueryHandler(ask_emails, pattern="^time_")],
            ASK_EMAILS: [CallbackQueryHandler(handle_email_selection, pattern="^(email_|confirm_emails)")],
            CONFIRM_SAVE: [CallbackQueryHandler(save_subscription, pattern="^save_sub")],
        },
        fallbacks=[
             CommandHandler("cancel", cancel_subscription),
             CallbackQueryHandler(cancel_subscription, pattern="^cancel_sub")
        ],
    )