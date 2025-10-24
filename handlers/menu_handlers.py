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

# Импорт хендлеров из других модулей, как в вашем проекте
from handlers.subscription_management_handler import my_subscriptions_command 

# ❗️ ИМПОРТ НОВОЙ ЛОГИКИ ИЗ TRAIN.PY
# Используем относительный импорт, если оба файла находятся в одной директории 'handlers'
from .train import train_cmd 

logger = get_logger(__name__)

# --- Константы для кнопок ---
BUTTON_DISLOCATION = "📦 Дислокация"
BUTTON_SUBSCRIPTIONS = "📂 Мои подписки"
BUTTON_TRAINS = "🚆 Мои поезда" # Скрытая для обычных
BUTTON_SETTINGS = "⚙️ Настройки" # Скрытая для обычных

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
        [KeyboardButton(BUTTON_SUBSCRIPTIONS)],
        [KeyboardButton(BUTTON_SETTINGS)]
    ],
    resize_keyboard=True
)

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

# --- Обработчик кнопок ReplyKeyboard (reply_keyboard_handler) ---

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок ReplyKeyboard."""
    if not update.message or not update.message.text or not update.effective_user:
         return 
         
    text = update.message.text.strip()
    user = update.effective_user
    is_admin = user.id == ADMIN_CHAT_ID
    
    logger.info(f"[Menu] Пользователь {user.id} нажал кнопку: {text}")

    # Логика для кнопки "📦 Дислокация"
    if BUTTON_DISLOCATION in text:
        # NOTE: Обычно здесь нужен переход в ConversationHandler для ожидания ввода
        await update.message.reply_text("Введите номер контейнера или вагона для поиска:")
        
    # Логика для кнопки "📂 Мои подписки"
    elif BUTTON_SUBSCRIPTIONS in text:
        await update.message.reply_text("Загрузка списка подписок...")
        await my_subscriptions_command(update, context) 
    
    # Логика для кнопок "🚆 Мои поезда" и "⚙️ Настройки" (только для админа)
    elif BUTTON_TRAINS in text or BUTTON_SETTINGS in text:
        if is_admin:
            if BUTTON_TRAINS in text:
                # ❗️❗️❗️ ИЗМЕНЕННАЯ ЛОГИКА ДЛЯ "МОИ ПОЕЗДА" ❗️❗️❗️
                # Вызываем train_cmd. Так как аргументов нет, он запустит show_train_list, 
                # который покажет Inline-меню со списком поездов.
                logger.info(f"[Menu] Админ {user.id} запускает логику /train через кнопку.")
                # Поскольку train_cmd ожидает update.message, и мы его имеем,
                # это должно корректно запустить процесс.
                return await train_cmd(update, context)
            
            elif BUTTON_SETTINGS in text:
                # Админ получает меню настроек
                await update.message.reply_text("Выберите настройки: email, уведомления и т.д.")
        else:
            # Обычный пользователь нажал кнопку, которую не должен был видеть
            await update.message.reply_text("⛔️ Доступ запрещён. Обновляю меню...")
            await start(update, context) # Перезагружаем меню с USER_KEYBOARD

    return