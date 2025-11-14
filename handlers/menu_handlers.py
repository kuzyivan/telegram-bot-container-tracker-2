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
from handlers.subscription_management_handler import my_subscriptions_command 
from .train import train_cmd 
from handlers.admin.panel import admin_panel
# --- ⭐️ УДАЛЯЕМ event_emails_menu, ОН БОЛЬШЕ ЗДЕСЬ НЕ НУЖЕН ---
from handlers.admin.uploads import upload_file_command
from handlers.email_management_handler import my_emails_command
from handlers.dislocation_handlers import handle_message 

# --- ⭐️ НОВЫЙ ИМПОРТ СОСТОЯНИЙ ⭐️ ---
from handlers.admin.event_email_handler import (
    MAIN_MENU as EVENT_EMAIL_MENU, 
    AWAITING_EMAIL_TO_ADD, 
    AWAITING_DELETE_CHOICE
)
# --- 🏁
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
    Обрабатывает ВСЕ текстовые сообщения, не являющиеся командами (в group=1).
    Выполняет роль диспетчера: сначала проверяет кнопки меню, 
    затем (если кнопки не нажаты) передает управление 
    обработчику дислокации (handle_message).
    """
    if not update.message or not update.message.text or not update.effective_user:
         return 
         
    text = update.message.text.strip()
    user = update.effective_user
    is_admin = user.id == ADMIN_CHAT_ID
    
    # --- 🚨 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ПРОВЕРКА ЗАВЕРШЕНИЯ ДИАЛОГА (ПЕРВЫЙ УРОВЕНЬ) 🚨
    # Проверяем, был ли только что установлен маркер завершения диалога.
    # pop() проверяет наличие и удаляет маркер за одну операцию.
    if context.user_data and context.user_data.pop('just_finished_conversation', False):
        logger.debug("[Menu] reply_keyboard_handler проигнорирован: только что завершился ConversationHandler.")
        return # <- Выходим, предотвращая вызов handle_message
        
    # --- ⭐️ УНИВЕРСАЛЬНЫЙ ПРЕДОХРАНИТЕЛЬ: УСТУПАЕМ АКТИВНОМУ ДИАЛОГУ ⭐️ ---
    if context.user_data:
        # 🚨 НОВАЯ ПРОВЕРКА: Проверяем явный маркер distance 🚨
        if context.user_data.get('is_distance_active'):
             logger.debug("[Menu] Уступаем активному диалогу /distance (маркер).")
             return

        # 🚨 НОВАЯ ПРОВЕРКА: Проверяем явный маркер broadcast
        if context.user_data.get('is_broadcast_active'):
             logger.debug("[Menu] Уступаем активному диалогу /broadcast (маркер).")
             return


        # Список имен всех ConversationHandler в приложении
        active_dialogs = [
            # 'distance_conversation' теперь проверяется маркером выше
            'add_containers_conversation',
            'remove_containers_conversation',
            'add_subscription_conversation'
        ]

        
        # Если имя любого диалога есть в user_data, то он активен
        if any(name in context.user_data for name in active_dialogs):
             logger.debug(f"[Menu] Уступаем активному диалогу: {', '.join([k for k in context.user_data.keys() if k in active_dialogs])}")
             return

        # Специальная проверка для диалога email-событий (через маркеры)
        if (EVENT_EMAIL_MENU in context.user_data or 
            AWAITING_EMAIL_TO_ADD in context.user_data or 
            AWAITING_DELETE_CHOICE in context.user_data):
            logger.debug("[Menu] Уступаем диалогу event_emails.")
            return
    # --- 🏁 КОНЕЦ ПРЕДОХРАНИТЕЛЯ 🏁 ---
    
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

    # --- ⭐️ ВАЖНО: ЭТОТ БЛОК ТЕПЕРЬ ПУСТОЙ ⭐️ ---
    # Кнопка "Email-событий" теперь перехватывается ConversationHandler-ом
    # в group=0, поэтому этот код никогда не выполнится.
    elif is_admin and BUTTON_SETTINGS_EVENT_EMAILS in text:
        # Этот код не должен выполниться, но мы его оставим
        # на случай, если ConversationHandler не сработает.
        logger.warning("[Menu] ConversationHandler для Email-событий не сработал. Вызов через reply_keyboard_handler.")
        # await event_emails_menu(update, context) # <--- УДАЛЕНО
        pass

    elif is_admin and BUTTON_SETTINGS_UPLOAD in text:
        await upload_file_command(update, context)

    elif is_admin and BUTTON_SETTINGS_MY_EMAILS in text:
        await my_emails_command(update, context) 

    # --- 4. Если ни одна кнопка не нажата -> это запрос Дислокации ---
    else:
        # Дополнительно проверяем, что это не команда, которую мы могли пропустить
        if text.startswith('/'):
            # Можно добавить логирование о неизвестной команде
            logger.debug(f"[Menu] Проигнорирована неизвестная команда: {text}")
            return

        logger.debug(f"[Menu] Текст '{text}' не является кнопкой. Передача в handle_message (дислокация).")
        await handle_message(update, context)

    return