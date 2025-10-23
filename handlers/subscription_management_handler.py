# handlers/subscription_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from queries.subscription_queries import get_user_subscriptions, delete_subscription, get_subscription_details
from queries.user_queries import register_user_if_not_exists 
from logger import get_logger

# NOTE: Импорты из handlers.menu_handlers удалены для предотвращения Circular Import

logger = get_logger(__name__)

async def my_subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message and not update.callback_query or not update.effective_user: # Учитываем CallbackQuery
        return
    
    # --- ИСПРАВЛЕНИЕ: Регистрируем пользователя перед запросом его подписок ---
    await register_user_if_not_exists(update.effective_user) 
    # --------------------------------------------------------------------------
    
    subs = await get_user_subscriptions(update.effective_user.id)
    keyboard = []
    text = "📂 *Ваши подписки*\n\n"
    if not subs:
        text += "У вас пока нет активных подписок."
    else:
        text += "Выберите подписку для управления:"
        for sub in subs:
            # ИСПРАВЛЕНО: Используем sub.id вместо sub.display_id
            keyboard.append([InlineKeyboardButton(f"{sub.subscription_name} ({sub.id})", callback_data=f"sub_menu_{sub.id}")]) 
    keyboard.append([InlineKeyboardButton("➕ Создать новую подписку", callback_data="create_sub_start")])
    
    # Отправляем сообщение в зависимости от того, откуда пришел вызов (сообщение или колбэк)
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif update.callback_query:
         # Если вызвано из колбэка, отправляем новое сообщение
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

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
        
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Извлекаем строку email из объекта UserEmail
    # sub.target_emails содержит объекты SubscriptionEmail, которые содержат .email (объект UserEmail)
    email_list = [sub_email.email.email for sub_email in sub.target_emails]
    
    emails_text = '`' + '`, `'.join(email_list) + '`' if email_list else 'Только в Telegram'
    status_text = 'Активна ✅' if sub.is_active is True else 'Неактивна ⏸️'
    containers_count = len(sub.containers) if sub.containers is not None else 0
    text = (
        f"⚙️ *Управление подпиской:*\n"
        f"*{sub.subscription_name}* `({sub.id})`\n\n" # ИСПРАВЛЕНО: Используем sub.id
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
            # ИСПРАВЛЕНО: Используем sub.id
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
