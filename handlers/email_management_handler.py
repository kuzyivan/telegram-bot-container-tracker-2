# handlers/email_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from queries.user_queries import get_user_emails, add_unverified_email, delete_user_email, register_user_if_not_exists, generate_and_save_verification_code, verify_code_and_activate_email, delete_unverified_email
from logger import get_logger
from handlers.menu_handlers import reply_keyboard_handler
import asyncio
from utils.email_sender import send_email, generate_verification_email

logger = get_logger(__name__)
# Обновлены состояния
(ADD_EMAIL, AWAIT_VERIFICATION_CODE) = range(2)
EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
CODE_REGEX = r'^\d{6}$' # Код подтверждения - 6 цифр

# --- Вспомогательные функции для меню ---

async def build_email_management_menu(telegram_id: int, intro_text: str) -> dict:
    # Запрос теперь фильтрует только ПОДТВЕРЖДЕННЫЕ адреса
    user_emails = await get_user_emails(telegram_id) 
    keyboard = []
    text = f"{intro_text}\n\n"
    if user_emails:
        text += "Сохраненные адреса:\n"
        for email in user_emails:
            # ✅ Все адреса в этом меню уже подтверждены
            text += f"• `{email.email}`\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {email.email}", callback_data=f"delete_email_{email.id}")])
    else:
        text += "У вас пока нет сохраненных email-адресов.\n"
    keyboard.append([InlineKeyboardButton("➕ Добавить новый Email", callback_data="add_email_start")])
    return {"text": text, "reply_markup": InlineKeyboardMarkup(keyboard)}

# --- Хендлеры команд (Точка входа) ---

async def my_emails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    
    await register_user_if_not_exists(update.effective_user) 

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

# --- Диалог добавления (Conversation Handler) ---

async def add_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query: return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("Пожалуйста, отправьте email-адрес, который хотите добавить. Для отмены введите /cancel.")
    return ADD_EMAIL

async def add_email_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Получает email, сохраняет его как неподтвержденный, отправляет код."""
    if not update.message or not update.message.text or not update.effective_user: return ConversationHandler.END
    
    email = update.message.text.strip()
    user_id = update.effective_user.id

    if not re.fullmatch(EMAIL_REGEX, email):
        await update.message.reply_text("⛔️ Кажется, это не похоже на email. Попробуйте еще раз или введите /cancel для отмены.")
        return ADD_EMAIL
        
    # 1. Сохраняем адрес как неподтвержденный
    unverified_email_obj = await add_unverified_email(user_id, email)
    if unverified_email_obj is None:
        # Если None, значит, адрес уже есть и подтвержден у этого пользователя
        await update.message.reply_text(f"⚠️ Email `{email}` уже был в вашем списке и подтвержден. Введите другой адрес или /cancel.", parse_mode='Markdown')
        return ADD_EMAIL

    # 2. Генерируем и сохраняем код
    code = await generate_and_save_verification_code(user_id, email)
    
    # 3. Отправляем код по почте (фоново)
    subject, body = generate_verification_email(code, user_id)
    # Вызываем синхронную send_email в отдельном потоке
    # ИСПРАВЛЕНИЕ: Вызов остаётся корректным, так как send_email теперь синхронна
    await asyncio.to_thread(send_email, to=email, subject=subject, body=body, attachments=None)

    # 4. Просим ввести код
    context.user_data['email_to_verify'] = email
    await update.message.reply_text(
        f"✅ На адрес `{email}` отправлен 6-значный код подтверждения.\n"
        "Пожалуйста, введите этот код в чат. Код действует 10 минут. Для отмены введите /cancel.",
        parse_mode='Markdown'
    )
    return AWAIT_VERIFICATION_CODE

async def receive_verification_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: Получает код и активирует email."""
    if not update.message or not update.message.text or not update.effective_user: return ConversationHandler.END
    
    code = update.message.text.strip()
    user_id = update.effective_user.id
    email_to_verify = context.user_data.get('email_to_verify')

    if not re.fullmatch(CODE_REGEX, code):
        await update.message.reply_text("⛔️ Код должен состоять из 6 цифр. Попробуйте еще раз или введите /cancel для отмены.")
        return AWAIT_VERIFICATION_CODE
        
    if not email_to_verify:
        await update.message.reply_text("❌ Ошибка: Не удалось найти адрес для подтверждения. Начните снова с /my_emails.")
        return ConversationHandler.END

    # 1. Проверяем код и активируем запись
    verified_email = await verify_code_and_activate_email(user_id, code)

    if verified_email:
        intro_text = f"✅ Email `{verified_email}` успешно подтвержден и добавлен в ваш список!"
    else:
        # Если код не прошел проверку (неверный код или истек срок действия)
        intro_text = "❌ Неверный код или истек срок его действия. Попробуйте ввести код еще раз или начните с /my_emails."
        await update.message.reply_text(intro_text)
        return AWAIT_VERIFICATION_CODE
    
    # 2. Завершаем диалог и показываем меню
    context.user_data.clear()
    menu_data = await build_email_management_menu(user_id, intro_text)
    await update.message.reply_text(menu_data["text"], reply_markup=menu_data["reply_markup"], parse_mode='Markdown')
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user: return ConversationHandler.END
    
    # Очистка неподтвержденного email и кодов
    email_to_clear = context.user_data.get('email_to_verify')
    await delete_unverified_email(update.effective_user.id, email_to_clear)

    await update.message.reply_text("Действие отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_and_reroute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user: return ConversationHandler.END
    
    # Очистка неподтвержденного email и кодов
    email_to_clear = context.user_data.get('email_to_verify')
    await delete_unverified_email(update.effective_user.id, email_to_clear)

    await update.message.reply_text("Действие отменено. Выполняю команду из меню...")
    await reply_keyboard_handler(update, context)
    context.user_data.clear()
    return ConversationHandler.END

def get_email_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_email_start, pattern="^add_email_start$")],
        states={
            # Шаг 1: Получаем Email
            ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_email_receive)],
            # Шаг 2: Получаем код подтверждения
            AWAIT_VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_verification_code)]
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
