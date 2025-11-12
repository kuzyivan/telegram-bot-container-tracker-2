# handlers/admin/event_email_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from telegram.error import BadRequest

from logger import get_logger
from handlers.admin.utils import admin_only_handler
from queries.event_queries import (
    get_global_email_rules, 
    add_global_email_rule, 
    delete_event_rule_by_id
)

# --- ⭐️ НОВЫЙ ИМПОРТ ⭐️ ---
# Импортируем текст кнопки из menu_handlers
from handlers.menu_handlers import BUTTON_SETTINGS_EVENT_EMAILS
# --- ⭐️

logger = get_logger(__name__)

# Состояния для диалога
(MAIN_MENU, AWAITING_EMAIL_TO_ADD, AWAITING_DELETE_CHOICE) = range(20, 23)

EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

# --- Вспомогательная функция: Построение главного меню ---

async def build_and_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, intro_text: str = ""):
    """
    Получает актуальные email из БД и отображает главное меню.
    """
    if not await admin_only_handler(update, context):
        return ConversationHandler.END

    recipients = await get_global_email_rules()
    
    email_list_text = ""
    if not recipients:
        email_list_text = "Список пуст."
    else:
        email_list_text = "\n".join(f"• `{rcp.recipient_email}`" for rcp in recipients)
    
    text = (
        f"{intro_text}\n\n"
        "📧 **Получатели уведомлений о выгрузке (Global):**\n"
        f"{email_list_text}\n\n"
        "Выберите действие:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить Email", callback_data="event_email_add"),
            InlineKeyboardButton("🗑️ Удалить Email", callback_data="event_email_delete_menu")
        ],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="event_email_cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сохраняем состояние в user_data, чтобы reply_keyboard_handler (group 1) "увидел" его
    if context.user_data is not None:
        context.user_data[MAIN_MENU] = True # Маркер того, что мы в этом меню
    
    # Отправляем или редактируем сообщение
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Ошибка в build_and_show_menu: {e}")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    return MAIN_MENU

# --- Точка входа ---

async def event_emails_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Точка входа /event_emails ИЛИ нажатия кнопки. Показывает главное меню.
    """
    if context.user_data:
        context.user_data.clear()
        
    return await build_and_show_menu(update, context, intro_text="Управление Email для событий поезда.")

# --- Логика добавления ---

async def prompt_for_email_to_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Запрашивает E-mail для добавления.
    """
    query = update.callback_query
    if not query:
        return MAIN_MENU
    
    # Обновляем маркеры состояния
    if context.user_data is not None:
        context.user_data.pop(MAIN_MENU, None)
        context.user_data[AWAITING_EMAIL_TO_ADD] = True
        
    await query.answer()
    await query.edit_message_text(
        "Пожалуйста, отправьте E-mail адрес, который хотите **добавить** в список рассылки."
        "\n\nДля отмены введите /cancel."
    )
    return AWAITING_EMAIL_TO_ADD

async def handle_new_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает введенный E-mail, добавляет в БД и возвращает в меню.
    """
    if not update.message or not update.message.text:
        return AWAITING_EMAIL_TO_ADD

    email_to_add = update.message.text.strip()
    
    if not re.fullmatch(EMAIL_REGEX, email_to_add):
        await update.message.reply_text(
            "⛔️ Это не похоже на E-mail. Попробуйте еще раз или введите /cancel."
        )
        return AWAITING_EMAIL_TO_ADD

    success = await add_global_email_rule(email_to_add)
    
    if success:
        intro_text = f"✅ Email `{email_to_add}` успешно добавлен."
    else:
        intro_text = f"⚠️ Email `{email_to_add}` уже был в списке."
    
    # Очищаем маркер состояния
    if context.user_data is not None:
        context.user_data.pop(AWAITING_EMAIL_TO_ADD, None)
        
    return await build_and_show_menu(update, context, intro_text=intro_text)

# --- Логика удаления ---

async def prompt_for_email_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показывает список E-mail в виде кнопок для удаления.
    """
    query = update.callback_query
    if not query:
        return MAIN_MENU
    await query.answer()

    # Обновляем маркеры состояния
    if context.user_data is not None:
        context.user_data.pop(MAIN_MENU, None)
        context.user_data[AWAITING_DELETE_CHOICE] = True

    recipients = await get_global_email_rules()
    if not recipients:
        # Очищаем маркер
        if context.user_data is not None:
            context.user_data.pop(AWAITING_DELETE_CHOICE, None)
        return await build_and_show_menu(update, context, intro_text="Нечего удалять. Список пуст.")

    keyboard = []
    text = "Нажмите на E-mail, который хотите **удалить**:"
    
    for rcp in recipients:
        # callback_data="event_email_delete_id_{ID_ПРАВИЛА}"
        keyboard.append([
            InlineKeyboardButton(f"🗑️ {rcp.recipient_email}", callback_data=f"event_email_delete_id_{rcp.id}")
        ])
        
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="event_email_back")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return AWAITING_DELETE_CHOICE

async def handle_delete_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Удаляет E-mail (по ID правила) и возвращает в меню.
    """
    query = update.callback_query
    if not query or not query.data:
        return AWAITING_DELETE_CHOICE
    
    await query.answer()
    
    try:
        rule_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        # Очищаем маркер
        if context.user_data is not None:
            context.user_data.pop(AWAITING_DELETE_CHOICE, None)
        return await build_and_show_menu(update, context, intro_text="❌ Ошибка: Некорректный ID для удаления.")
        
    success = await delete_event_rule_by_id(rule_id)
    
    if success:
        intro_text = "✅ Email успешно удален."
    else:
        intro_text = "❌ Ошибка: Не удалось удалить Email."
    
    # Очищаем маркер
    if context.user_data is not None:
        context.user_data.pop(AWAITING_DELETE_CHOICE, None)
        
    return await build_and_show_menu(update, context, intro_text=intro_text)

# --- Отмена / Выход ---

async def cancel_event_email_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Завершает диалог.
    """
    if context.user_data:
        context.user_data.clear()
        
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text("Управление E-mail адресами закрыто.")
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                logger.error(f"Ошибка в cancel_event_email_dialog: {e}")

    elif update.message:
        await update.message.reply_text("Отменено.")

    return ConversationHandler.END

# --- Функция регистрации ---

def get_event_email_handlers() -> list:
    """
    Возвращает список хендлеров (CommandHandler + ConversationHandler) для bot.py
    """
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("event_emails", event_emails_menu),
            # --- ⭐️ НОВАЯ ТОЧКА ВХОДА ⭐️ ---
            # Теперь диалог будет запускаться и по нажатию кнопки из ReplyKeyboard
            MessageHandler(
                filters.TEXT & filters.Regex(f"^{re.escape(BUTTON_SETTINGS_EVENT_EMAILS)}$"), 
                event_emails_menu
            )
            # --- ⭐️
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(prompt_for_email_to_add, pattern="^event_email_add$"),
                CallbackQueryHandler(prompt_for_email_to_delete, pattern="^event_email_delete_menu$"),
            ],
            AWAITING_EMAIL_TO_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_email_input)
            ],
            AWAITING_DELETE_CHOICE: [
                CallbackQueryHandler(handle_delete_email_callback, pattern="^event_email_delete_id_"),
                # "Назад" просто возвращает в главное меню
                CallbackQueryHandler(event_emails_menu, pattern="^event_email_back$") 
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_event_email_dialog),
            CallbackQueryHandler(cancel_event_email_dialog, pattern="^event_email_cancel$")
        ],
        allow_reentry=True 
    )
    
    return [conv_handler]