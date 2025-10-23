# handlers/email_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from queries.user_queries import get_user_emails, add_user_email, delete_user_email, register_user_if_not_exists
from logger import get_logger
from handlers.menu_handlers import reply_keyboard_handler

logger = get_logger(__name__)
ADD_EMAIL = range(1)
EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

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
    
    # --- ИСПРАВЛЕНИЕ: Регистрируем пользователя перед запросом его emails ---
    await register_user_if_not_exists(update.effective_user) 
    # -----------------------------------------------------------------------

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

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return ConversationHandler.END
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

async def cancel_and_reroute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return ConversationHandler.END
    await update.message.reply_text("Действие отменено. Выполняю команду из меню...")
    await reply_keyboard_handler(update, context)
    return ConversationHandler.END

def get_email_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_email_start, pattern="^add_email_start$")],
        states={
            ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email_receive)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            MessageHandler(filters.Regex("^(📦 Дислокация|📂 Мои подписки)$"), cancel_and_reroute)
        ],
    )

def get_email_command_handlers():
    return [
        CommandHandler("my_emails", my_emails_command),
        CallbackQueryHandler(delete_email_callback, pattern="^delete_email_"),
    ]
