# handlers/admin/panel.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from logger import get_logger

# ✅ ИСПРАВЛЕНИЕ: Удаляем несуществующие импорты 'force_notify_cmd' и 'test_notify_cmd'
from .exports import stats, tracking, exportstats 
# from .notifications import force_notify_cmd, test_notify_cmd # <-- УДАЛЯЕМ ЭТУ СТРОКУ

logger = get_logger(__name__)

# --- Основная панель ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает панель администратора."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        logger.warning(f"Попытка доступа к админ-панели от {update.effective_user.id}")
        return

    text = "🛠️ **Панель администратора**\n\nВыберите действие:"
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика за сутки", callback_data='admin_stats')],
        [
            InlineKeyboardButton("📤 Экспорт запросов", callback_data='admin_exportstats'),
            InlineKeyboardButton("📦 Экспорт подписок", callback_data='admin_tracking')
        ],
        # ✅ ИСПРАВЛЕНИЕ: Кнопки теперь будут вызывать команду, зарегистрированную в bot.py, 
        # или использовать колбэки, если они есть.
        [
            InlineKeyboardButton("🔔 Принудительная рассылка", callback_data='admin_force_notify'),
            InlineKeyboardButton("🧪 Тестовое уведомление", callback_data='admin_test_notify')
        ],
        [InlineKeyboardButton("🔄 Скрыть", callback_data='admin_hide')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id 
        )
    elif update.callback_query:
         await update.callback_query.message.edit_text(
             text, 
             reply_markup=reply_markup, 
             parse_mode='Markdown'
         )

# --- Обработчик колбэков ---

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок на админ-панели."""
    query = update.callback_query
    
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    data = query.data
    
    if data == 'admin_stats':
        await stats(update, context) 
    elif data == 'admin_exportstats':
        await exportstats(update, context)
    elif data == 'admin_tracking':
        await tracking(update, context)
    elif data == 'admin_force_notify':
        # ✅ ИСПРАВЛЕНИЕ: Вместо вызова несуществующей команды, 
        # уведомляем пользователя, что нужно использовать команду /force_notify
        await query.message.reply_text("Для принудительной рассылки используйте команду /broadcast или /force_notify")
    elif data == 'admin_test_notify':
        # ✅ ИСПРАВЛЕНИЕ: Аналогично, уведомляем о команде /test_notify
        await query.message.reply_text("Для тестового уведомления используйте команду /test_notify")
    elif data == 'admin_hide':
        await query.message.delete()