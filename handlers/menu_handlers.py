# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from logger import get_logger
import re

from handlers.subscription_management_handler import my_subscriptions_command 

logger = get_logger(__name__)

# --- Вспомогательные функции ---

# Клавиатура главного меню
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📦 Дислокация"), KeyboardButton("🚆 Мои поезда")],
        [KeyboardButton("📂 Мои подписки")],
        [KeyboardButton("⚙️ Настройки")]
    ],
    resize_keyboard=True
)

# --- Обработчики команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start, выводя главное меню."""
    if not update.message:
        return
    
    await update.message.reply_text(
        "Здравствуйте! Выберите действие в меню:",
        reply_markup=MAIN_KEYBOARD
    )

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает стикеры."""
    if update.message:
        await update.message.reply_text("Спасибо за стикер!")

# --- Обработчик кнопок ReplyKeyboard ---

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок ReplyKeyboard."""
    text = update.message.text.strip()
    user = update.effective_user
    
    logger.info(f"[Menu] Пользователь {user.id} нажал кнопку: {text}")

    # Логика для кнопки "📦 Дислокация"
    if "Дислокация" in text:
        await update.message.reply_text("Введите номер контейнера или вагона для поиска:")
        
    # Логика для кнопки "📂 Мои подписки"
    elif "подписки" in text:
        # Прямой вызов хендлера команды /my_subscriptions
        await update.message.reply_text("Загрузка списка подписок...")
        await my_subscriptions_command(update, context) 
    
    # Логика для кнопки "🚆 Мои поезда"
    elif "поезда" in text:
        # NOTE: В боте train_cmd - это ConversationHandler, запускаем его через /train
        await update.message.reply_text("Запущена команда /train. Введите номер поезда:")
        
    # Логика для кнопки "⚙️ Настройки"
    elif "Настройки" in text:
         await update.message.reply_text("Выберите настройки: email, уведомления и т.д.")

    return