# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from logger import get_logger
import re

# Импорт ADMIN_CHAT_ID ИЗ config.py
import sys
import os
# Добавляем корень проекта в путь, если он не был добавлен ранее
sys.path.append(os.path.join(os.path.dirname(__file__), '..')) 
from config import ADMIN_CHAT_ID 

# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
# Импорт хендлеров из других модулей, как в вашем проекте
from handlers.subscription_management_handler import my_subscriptions_command 
from .train import train_cmd 
# Импортируем функции, которые будут вызываться из меню настроек
from handlers.admin.panel import admin_panel
from handlers.admin.event_email_handler import event_emails_menu
from handlers.admin.uploads import upload_file_command
from handlers.email_management_handler import my_emails_command
# Импортируем главный обработчик дислокации
from handlers.dislocation_handlers import handle_message 
# --- 🏁 КОНЕЦ ИМПОРТОВ ---

logger = get_logger(__name__)

# --- Константы для кнопок ---
BUTTON_DISLOCATION = "📦 Дислокация"
BUTTON_SUBSCRIPTIONS = "📂 Мои подписки"
BUTTON_TRAINS = "🚆 Мои поезда" 
BUTTON_SETTINGS = "⚙️ Настройки" 

# --- ✅ НОВЫЕ КОНСТАНТЫ ДЛЯ МЕНЮ НАСТРОЕК ---
BUTTON_SETTINGS_ADMIN = "🛠️ Админ-панель"
BUTTON_SETTINGS_EVENT_EMAILS = "📬 Email-событий"
BUTTON_SETTINGS_UPLOAD = "📤 Загрузка файлов"
BUTTON_SETTINGS_MY_EMAILS = "📧 Мои Email-адреса"
BUTTON_BACK_TO_MAIN = "🔙 Назад в главное меню"
# --- 🏁 КОНЕЦ НОВЫХ КОНСТАНТ ---

# --- Клавиатуры ---

# Клавиатура для всех пользователей (только базовый функционал)
USER_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BUTTON_DISLOCATION)],
        [KeyboardButton(BUTTON_SUBSCRIPTIONS)]
    ],
    resize_keyboard=True
)

# Клавиатура для администратора (включает "Мои поезда" и "Настройки")
ADMIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BUTTON_DISLOCATION), KeyboardButton(BUTTON_TRAINS)],
        [KeyboardButton(BUTTON_SUBSCRIPTIONS), KeyboardButton(BUTTON_SETTINGS)],
    ],
    resize_keyboard=True
)

# --- ✅ НОВАЯ КЛАВИАТУРА МЕНЮ НАСТРОЕК ---
ADMIN_SETTINGS_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BUTTON_SETTINGS_ADMIN)],
        [KeyboardButton(BUTTON_SETTINGS_EVENT_EMAILS)],
        [KeyboardButton(BUTTON_SETTINGS_UPLOAD)],
        [KeyboardButton(BUTTON_SETTINGS_MY_EMAILS)],
        [KeyboardButton(BUTTON_BACK_TO_MAIN)]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите настройку..."
)
# --- 🏁 КОНЕЦ НОВОЙ КЛАВИАТУРЫ ---


# --- Обработчики команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start, выводя главное меню."""
    if not update.message or not update.effective_user:
        return
    
    # Выбор клавиатуры в зависимости от ID пользователя
    is_admin = update.effective_user.id == ADMIN_CHAT_ID
    keyboard = ADMIN_KEYBOARD if is_admin else USER_KEYBOARD
    
    await update.message.reply_text(
        "Здравствуйте! Выберите действие в меню:",
        reply_markup=keyboard
    )

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает стикеры."""
    if update.message:
        await update.message.reply_text("Спасибо за стикер!")

# --- ✅ ОБНОВЛЕННЫЙ ОБРАБОТЧИК КНОПОК (ЕДИНЫЙ ДИСПЕТЧЕР) ---

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает ВСЕ текстовые сообщения, не являющиеся командами.
    Выполняет роль диспетчера: сначала проверяет кнопки меню, 
    затем (если кнопки не нажаты) передает управление 
    обработчику дислокации (handle_message).
    """
    if not update.message or not update.message.text or not update.effective_user:
         return 
         
    text = update.message.text.strip()
    user = update.effective_user
    is_admin = user.id == ADMIN_CHAT_ID
    
    # --- ✅ ПРЕДОХРАНИТЕЛЬ (Guard Clause) ---
    # Проверяем, не активен ли сейчас какой-либо ConversationHandler.
    # Если да, этот обработчик не должен "красть" у него сообщения.
    if context.user_data:
        # Ключи из tracking_handlers
        if 'sub_name' in context.user_data or 'sub_containers' in context.user_data:
            return # Уступаем диалогу создания подписки
        # Ключи из event_email_handler
        if text.startswith('/'): # Позволяем /cancel работать
             pass
        elif MAIN_MENU in context.user_data or AWAITING_EMAIL_TO_ADD in context.user_data or AWAITING_DELETE_CHOICE in context.user_data:
             return # Уступаем диалогу управления E-mail
        # (Можно добавить другие ключи по мере необходимости)
    # --- 🏁 КОНЕЦ ПРЕДОХРАНИТЕЛЯ ---
    
    logger.info(f"[Menu] Пользователь {user.id} нажал кнопку или ввел текст: {text}")

    # --- 1. Обработка кнопок Главного Меню ---
    if BUTTON_DISLOCATION in text:
        await update.message.reply_text("Введите номер контейнера или вагона для поиска:")
        
    elif BUTTON_SUBSCRIPTIONS in text:
        await update.message.reply_text("Загрузка списка подписок...")
        await my_subscriptions_command(update, context) 
    
    elif BUTTON_TRAINS in text:
        if is_admin:
            logger.info(f"[Menu] Админ {user.id} запускает логику /train через кнопку.")
            return await train_cmd(update, context)
        else:
            await update.message.reply_text("⛔️ Доступ запрещён.")

    # --- 2. Обработка переключения меню ---
    elif BUTTON_SETTINGS in text:
        if is_admin:
            await update.message.reply_text(
                "Выберите нужный раздел настроек:",
                reply_markup=ADMIN_SETTINGS_KEYBOARD # Показываем новое меню
            )
        else:
            await update.message.reply_text("⛔️ Доступ запрещён.")
            
    elif BUTTON_BACK_TO_MAIN in text:
        if is_admin:
            await start(update, context) # Показываем главное меню
        else:
            await update.message.reply_text("⛔️ Доступ запрещён.")

    # --- 3. Обработка кнопок Меню Настроек (только для Админа) ---
    elif is_admin and BUTTON_SETTINGS_ADMIN in text:
        await admin_panel(update, context)

    elif is_admin and BUTTON_SETTINGS_EVENT_EMAILS in text:
        # Эта функция ЗАПУСКАЕТ ConversationHandler
        await event_emails_menu(update, context) 

    elif is_admin and BUTTON_SETTINGS_UPLOAD in text:
        await upload_file_command(update, context)

    elif is_admin and BUTTON_SETTINGS_MY_EMAILS in text:
        # Убедимся, что /my_email - это /my_emails
        await my_emails_command(update, context) 

    # --- 4. Если ни одна кнопка не нажата -> это запрос Дислокации ---
    else:
        # Мы больше не используем Regex в bot.py
        # Вместо этого, если текст не совпал ни с одной кнопкой,
        # мы *предполагаем*, что это запрос дислокации,
        # и передаем управление в `handle_message`.
        
        logger.debug(f"[Menu] Текст '{text}' не является кнопкой. Передача в handle_message (дислокация).")
        await handle_message(update, context)

    return