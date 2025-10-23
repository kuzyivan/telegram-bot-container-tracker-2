# handlers/subscription_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from queries.user_queries import get_user_emails, add_user_email, delete_user_email
from queries.subscription_queries import get_user_subscriptions, delete_subscription, get_subscription_details
from logger import get_logger

logger = get_logger(__name__)
ADD_EMAIL = range(1)
EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# --- ФУНКЦИЯ, КОТОРУЮ НЕ УДАЕТСЯ ИМПОРТИРОВАТЬ ---
async def my_subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    subs = await get_user_subscriptions(update.effective_user.id)
    keyboard = []
    text = "📂 *Ваши подписки*\n\n"
    if not subs:
        text += "У вас пока нет активных подписок."
    else:
        text += "Выберите подписку для управления:"
        for sub in subs:
            # Используем sub.id вместо несуществующего sub.display_id
            keyboard.append([InlineKeyboardButton(f"{sub.subscription_name} ({sub.id})", callback_data=f"sub_menu_{sub.id}")]) 
    keyboard.append([InlineKeyboardButton("➕ Создать новую подписку", callback_data="create_sub_start")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
# --------------------------------------------------

async def build_email_management_menu(telegram_id: int, intro_text: str) -> dict:
    user_emails = await get_user_emails(telegram_id)
    keyboard = []
    text = f"{intro_text}\n\n"
    if user_emails:
        text += "Сохраненные адреса:\n"
        for email in user_emails:
            text += f"• `{email.email}`\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {email.email}", callback_data=f"delete_email_{email.id}")])
    else:
        text += "У вас пока нет сохраненных email-адресов.\n"
    keyboard.append([InlineKeyboardButton("➕ Добавить новый Email", callback_data="add_email_start")])
    return {"text": text, "reply_markup": InlineKeyboardMarkup(keyboard)}

async def my_emails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    menu_data = await build_email_management_menu(update.effective_user.id, "📧 *Управление Email-адресами*")
    await update.message.reply_text(menu_data["text"], reply_markup=menu_data["reply_markup"], parse_mode='Markdown')

async def delete_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user: return
    await query.answer()
    email_id = int(query.data.split("_")[-1])
    deleted = await delete_user_email(email_id, query.from_user.id)
    intro_text = "✅ Email успешно удален." if deleted else "❌ Не удалось удалить email."
    menu_data = await build_email_management_menu(query.from_user.id, intro_text)
    await query.edit_message_text(menu_data["text"], reply_markup=menu_data["reply_markup"], parse_mode='Markdown')

async def add_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("Пожалуйста, отправьте email-адрес, который хотите добавить. Для отмены введите /cancel.")
    return ADD_EMAIL

async def add_email_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user: return ConversationHandler.END
    email = update.message.text.strip()
    if not re.fullmatch(EMAIL_REGEX, email):
        await update.message.reply_text("⛔️ Кажется, это не похоже на email. Попробуйте еще раз или введите /cancel для отмены.")
        return ADD_EMAIL
    added_email = await add_user_email(update.effective_user.id, email)
    intro_text = f"✅ Новый email `{added_email.email}` успешно добавлен." if added_email else f"⚠️ Email `{email}` уже был в вашем списке."
    menu_data = await build_email_management_menu(update.effective_user.id, intro_text)
    await update.message.reply_text(menu_data["text"], reply_markup=menu_data["reply_markup"], parse_mode='Markdown')
    return ConversationHandler.END

# ЕДИНСТВЕННАЯ ФУНКЦИЯ ОТМЕНЫ ДЛЯ EMAIL
async def cancel_email_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет ввод email."""
    if not update.message: return ConversationHandler.END
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

def get_email_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_email_start, pattern="^add_email_start$")],
        states={
            ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email_receive)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_email_conversation),
        ],
    )

def get_email_command_handlers():
    return [
        CommandHandler("my_emails", my_emails_command),
        CallbackQueryHandler(delete_email_callback, pattern="^delete_email_"),
    ]


# --- ВОССТАНОВЛЕННЫЕ ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ ПОДПИСКАМИ ---

async def subscription_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.edit_message_text("❌ Ошибка: подписка не найдена или не принадлежит вам.")
        return
    email_list = [e.email for e in sub.target_emails]
    emails_text = '`' + '`, `'.join(email_list) + '`' if email_list else 'Только в Telegram'
    status_text = 'Активна ✅' if sub.is_active is True else 'Неактивна ⏸️'
    containers_count = len(sub.containers) if sub.containers is not None else 0
    text = (
        f"⚙️ *Управление подпиской:*\n"
        f"*{sub.subscription_name}* `({sub.id})`\n\n" 
        f"Статус: {status_text}\n"
        f"Время отчета: {sub.notification_time.strftime('%H:%M')}\n"
        f"Контейнеров: {containers_count} шт.\n"
        f"Email для отчетов: {emails_text}"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Показать контейнеры", callback_data=f"sub_show_{sub.id}")],
        [InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"sub_delete_{sub.id}")],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data="sub_back_to_list")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_containers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.answer("❌ Ошибка: подписка не найдена.", show_alert=True)
        return
    if not sub.containers or len(sub.containers) == 0:
        text = "В этой подписке нет контейнеров."
    else:
        container_list = "\n".join(f"`{c}`" for c in sub.containers)
        text = f"Контейнеры в подписке *{sub.subscription_name}*:\n{container_list}"
    if update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def delete_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
    deleted = await delete_subscription(subscription_id, query.from_user.id)
    if deleted:
        await query.edit_message_text("✅ Подписка успешно удалена.")
    else:
        await query.edit_message_text("❌ Не удалось удалить подписку.")

async def back_to_subscriptions_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    subs = await get_user_subscriptions(query.from_user.id)
    keyboard = []
    text = "📂 *Ваши подписки*\n\n"
    if not subs:
        text += "У вас пока нет активных подписок."
    else:
        text += "Выберите подписку для управления:"
        for sub in subs:
            keyboard.append([InlineKeyboardButton(f"{sub.subscription_name} ({sub.id})", callback_data=f"sub_menu_{sub.id}")])
    keyboard.append([InlineKeyboardButton("➕ Создать новую подписку", callback_data="create_sub_start")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


def get_subscription_management_handlers():
    return [
        CommandHandler("my_subscriptions", my_subscriptions_command),
        CallbackQueryHandler(subscription_menu_callback, pattern="^sub_menu_"),
        CallbackQueryHandler(show_containers_callback, pattern="^sub_show_"),
        CallbackQueryHandler(delete_subscription_callback, pattern="^sub_delete_"),
        CallbackQueryHandler(back_to_subscriptions_list_callback, pattern="^sub_back_to_list$"),
    ]