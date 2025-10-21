# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from logger import get_logger
import re

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
    
    # Введите здесь логику регистрации пользователя, если она не в register_user_if_not_exists
    
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
        # Вызываем команду /my_subscriptions (она должна быть зарегистрирована в bot.py)
        await context.application.update_queue.put(
             Update(
                 update_id=update.update_id,
                 message=update.message.effective_message,
                 callback_query=None,
                 my_chat_member=None,
                 edited_message=None,
                 channel_post=None,
                 edited_channel_post=None,
                 inline_query=None,
                 chosen_inline_result=None,
                 shipping_query=None,
                 pre_checkout_query=None,
                 poll=None,
                 poll_answer=None,
                 chat_member=None,
                 chat_join_request=None
             )
        )
        await update.message.reply_text("Запущена команда /my_subscriptions...")
    
    # Логика для кнопки "🚆 Мои поезда"
    elif "поезда" in text:
        await update.message.reply_text("Запущена команда /train. Введите номер поезда:")
        
    # Логика для кнопки "⚙️ Настройки"
    elif "Настройки" in text:
         await update.message.reply_text("Выберите настройки: email, уведомления и т.д.")

    return