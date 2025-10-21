# handlers/menu_handlers.py
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from logger import get_logger
# ✅ Исправляем импорт функции регистрации
from queries.user_queries import register_user_if_not_exists 
from utils.keyboards import main_menu_keyboard # Импортируем клавиатуру главного меню

logger = get_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и главное меню."""
    user = update.effective_user
    message = update.message

    if not user or not message:
        logger.warning("Команда /start вызвана без пользователя или сообщения.")
        return

    # Регистрируем или обновляем пользователя при каждом /start
    try:
        # ✅ Исправляем вызов функции регистрации
        await register_user_if_not_exists(user) 
    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя {user.id}: {e}", exc_info=True)
        # Не прерываем выполнение, просто логируем ошибку

    await message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        "Я бот для отслеживания контейнеров. Введите номер контейнера для поиска.",
        reply_markup=main_menu_keyboard # Показываем главное меню
    )

async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок главного меню (ReplyKeyboardMarkup)."""
    message = update.message
    user = update.effective_user

    if not message or not message.text or not user:
        return

    text = message.text

    if text == "📦 Отслеживание": # Или "Дислокация"
        await message.reply_text("Введите номер контейнера для поиска дислокации.")
    elif text == "📄 Мои подписки":
        # Здесь можно вызвать функцию, которая показывает список подписок
        # Например, импортировать и вызвать list_subscriptions из subscription_management_handler.py
        # await list_subscriptions(update, context) # Пример
        await message.reply_text("Функция 'Мои подписки' пока не реализована через кнопки.")
    elif text == "⚙️ Настройки":
         # TODO: Показать меню настроек (например, с кнопками управления Email)
         await message.reply_text("Раздел настроек (пока не реализован).")
    elif text == "🔙 Главное меню":
         await message.reply_text("Вы в главном меню.", reply_markup=main_menu_keyboard)
    # Добавьте обработку других кнопок, если они есть
    else:
        # Если текст не соответствует кнопке, считаем, что это поиск контейнера
        from .dislocation_handlers import handle_message # Локальный импорт для избежания цикла
        await handle_message(update, context)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
     """Отвечает на стикеры."""
     if update.message:
        await update.message.reply_text("Классный стикер! 👍")

# Можно добавить обработчики для других кнопок меню, если нужно