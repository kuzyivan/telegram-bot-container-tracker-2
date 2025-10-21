# handlers/admin/notifications.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler
from datetime import datetime
import os

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.admin_queries import get_data_for_test_notification
# ✅ ИСПРАВЛЕНИЕ: Импортируем только существующие функции
from utils.send_tracking import create_excel_file, get_vladivostok_filename 
from utils.notify import notify_admin

logger = get_logger(__name__)

# --- Состояния диалога (если есть) ---
# Предположим, что состояния для force_notify определены здесь
CHOOSING, TYPING_REPLY = range(2) 


# --- Обработчик /test_notify (Примерный код) ---

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует Excel-файл с данными для тестовой рассылки и отправляет его администратору."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    await update.message.reply_text("⏳ Собираю тестовые данные для рассылки...")
    logger.info("[TestNotify] Инициация сбора данных.")
    
    try:
        # Получаем данные в формате {sheet_name: [[row1], [row2]], ...}
        data_dict = await get_data_for_test_notification()
        
        if not data_dict:
            await update.message.reply_text("⚠️ Не найдено активных подписок для тестового отчета.")
            return

        # ✅ ИСПРАВЛЕНИЕ: Используем стандартную функцию create_excel_file 
        # Если create_excel_file не поддерживает мульти-листы, код может быть упрощен.
        # Поскольку у нас нет create_excel_multisheet, мы создадим ОДИН лист
        
        # ВРЕМЕННОЕ РЕШЕНИЕ: Создаем один Excel-файл с первым листом данных
        first_sheet_name = next(iter(data_dict))
        rows = data_dict[first_sheet_name]
        
        # Заголовки (предполагаем, что они известны или берутся из первого элемента)
        # Если нет заголовков в data_dict, используем заглушки
        headers = ['Контейнер', 'Отпр', 'Назн', 'Текущая', 'Операция', 'Дата', 'НаКладная', 'КМ', 'Прогноз', 'Вагон', 'Дорога']
        
        file_path = await asyncio.to_thread(
            create_excel_file,
            rows,
            headers
        )

        with open(file_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=get_vladivostok_filename(prefix="ТестРассылка"),
                caption=f"✅ Тестовый Excel-отчет (только первый лист данных)."
            )
        logger.info("[TestNotify] Тестовый Excel успешно отправлен.")

    except Exception as e:
        logger.exception(f"❌ Ошибка при создании тестового Excel: {e}")
        await update.message.reply_text("❌ Внутренняя ошибка при создании тестового Excel-отчета.")
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# --- Обработчик /force_notify (Примерный код) ---

async def force_notify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заглушка для force_notify, которая вызывает диалог (если он определен в bot.py)"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text("Введите текст для рассылки всем пользователям...")
    # Этот код обычно запускает ConversationHandler, который должен быть зарегистрирован в bot.py

# --- Регистрация хендлеров ---

def get_notification_handlers():
    return [
        CommandHandler("test_notify", test_notify),
        CommandHandler("force_notify", force_notify_cmd) # Заглушка, если диалог не определен
    ]