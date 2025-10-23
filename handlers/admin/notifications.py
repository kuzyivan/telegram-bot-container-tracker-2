from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler
from datetime import datetime, time
import os

from config import ADMIN_CHAT_ID
from logger import get_logger
from queries.admin_queries import get_data_for_test_notification
# ✅ ИСПРАВЛЕНИЕ: Импортируем только существующие функции
from utils.send_tracking import create_excel_file, get_vladivostok_filename 
from utils.notify import notify_admin
from services.notification_service import NotificationService # <-- НОВЫЙ ИМПОРТ
from handlers.admin.utils import admin_only_handler # <-- НОВЫЙ ИМПОРТ ДЛЯ ПРОВЕРКИ

logger = get_logger(__name__)

# --- Состояния диалога (если есть) ---
# Предположим, что состояния для force_notify определены здесь
CHOOSING, TYPING_REPLY = range(2) 


# --- Обработчик /test_notify (Примерный код) ---

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует Excel-файл с данными для тестовой рассылки и отправляет его администратору."""
    if not await admin_only_handler(update, context):
        return
    
    await update.message.reply_text("⏳ Собираю тестовые данные для рассылки...")
    logger.info("[TestNotify] Инициация сбора данных.")
    
    try:
        # Получаем данные в формате {sheet_name: [[row1], [row2]], ...}
        data_dict = await get_data_for_test_notification()
        
        if not data_dict:
            await update.message.reply_text("⚠️ Не найдено активных подписок для тестового отчета.")
            return

        # ВРЕМЕННОЕ РЕШЕНИЕ: Создаем один Excel-файл с первым листом данных
        first_sheet_name = next(iter(data_dict))
        rows = data_dict[first_sheet_name]
        
        # Заголовки (предполагаем, что они известны или берутся из первого элемента)
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

# --- НОВЫЙ ОБРАБОТЧИК ДЛЯ /force_notify ---

async def force_notify_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Принудительный запуск рассылки уведомлений для текущего часа (в UTC).
    Полностью повторяет логику job_send_notifications.
    """
    if not await admin_only_handler(update, context):
        return

    if update.effective_chat is None or update.effective_message is None:
        return

    # 1. Определение целевого времени в UTC, соответствующего формату в БД (09:00, 16:00 и т.д.)
    # Поскольку apscheduler использует cron с TZ="Asia/Vladivostok", но notification_time
    # в БД хранится как простое time без TZ (например, time(9, 0)),
    # мы будем искать подписки, соответствующие текущему часу по UTC.
    
    # ⚠️ ВНИМАНИЕ: Если подписки созданы на 09:00 Vladivostok, то принудительно
    # запустить их можно только в 09:00 Vladivostok (02:00 UTC).
    # Для простоты тестирования мы ищем подписки, соответствующие часам 09:00 и 16:00
    # независимо от текущего времени, если команда вызвана без аргумента.
    
    target_times = [time(9, 0), time(16, 0)] # Ищем подписки на стандартное время
    
    # Если передан аргумент, используем его (например, /force_notify 09:00)
    if context.args:
        try:
            hour, minute = map(int, context.args[0].split(':'))
            target_time = time(hour, minute)
            target_times = [target_time]
        except ValueError:
            await update.effective_message.reply_text("❌ Неверный формат времени. Используйте /force_notify [ЧЧ:ММ] или без аргументов.")
            return

    results = []
    
    await update.effective_message.reply_text(
        f"⏳ Запуск принудительной рассылки для времени **{', '.join([t.strftime('%H:%M') for t in target_times])}**...",
        parse_mode="Markdown"
    )

    try:
        service = NotificationService(context.bot)
        
        for target_time in target_times:
            time_str = target_time.strftime('%H:%M')
            logger.info(f"[Force Notify] Инициация рассылки для времени {time_str}...")
            
            sent_count, total_count = await service.send_scheduled_notifications(target_time)
            
            results.append({
                "time_str": time_str, 
                "sent_count": sent_count, 
                "total_count": total_count
            })

        final_message = "✅ **Принудительная рассылка завершена.**\n"
        for res in results:
             final_message += (
                 f"Время **{res['time_str']}**:\n"
                 f"  Обработано подписок: **{res['total_count']}**\n"
                 f"  Отправлено сообщений: **{res['sent_count']}**\n"
             )

        logger.info(f"[Force Notify] Рассылка завершена. Сводка: {final_message.replace('**', '')}")
        await update.effective_message.reply_text(final_message, parse_mode="Markdown")

    except Exception as e:
        error_message = f"❌ Критическая ошибка при принудительной рассылке: `{e}`"
        logger.critical(error_message, exc_info=True)
        await update.effective_message.reply_text(error_message, parse_mode="Markdown")


# --- Регистрация хендлеров ---

def get_notification_handlers():
    # ✅ Добавляем новый обработчик в список
    return [
        CommandHandler("test_notify", test_notify),
        CommandHandler("force_notify", force_notify_handler) 
    ]
# --- Конец НОВОГО ОБРАБОТЧИКА ---
