# handlers/admin/uploads.py
import os
import re
import asyncio
from pathlib import Path
from datetime import datetime # <--- ДОБАВЛЕН ИМПОРТ
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    MessageHandler, CallbackQueryHandler, filters
)

from config import ADMIN_CHAT_ID
from logger import get_logger
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_DIR as DISLOCATION_DOWNLOAD_FOLDER 
from services.terminal_importer import (
    import_train_from_excel, 
    extract_train_code_from_filename, 
    process_terminal_report_file,
    _collect_containers_from_excel # Импортируем сборщик контейнеров
)
from services.file_utils import save_temp_file_async
from utils.notify import notify_admin

# --- ✅ Импортируем новую функцию ---
from queries.train_queries import upsert_train_on_upload 

logger = get_logger(__name__)

# Состояния для диалога
ASK_OVERLOAD_CONFIRM, ASK_STATION_NAME = range(2)

TERMINAL_REPORT_PATTERN = r'A-Terminal.*\.xlsx$'


async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информирует администратора о способе загрузки файлов."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message:
        return

    text = (
        "**Инструкция по загрузке файлов:**\n\n"
        "1. **Файлы дислокации (103):**\n"
        "   - Имя файла должно начинаться с `103_`.\n"
        "2. **Файлы поезда (KXX-YYY):**\n"
        "   - Имя файла должно содержать код поезда (например, `КП К25-073 Селятино.xlsx`).\n"
        "3. **Отчет терминала (A-Terminal):**\n"
        "   - Имя файла должно содержать `A-Terminal`.\n\n"
        "Отправьте Excel-файл как документ."
    )
    await update.message.reply_text(text, parse_mode='Markdown')


# --- НОВЫЙ ДИАЛОГ ЗАГРУЗКИ ---

async def handle_admin_document_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Точка входа в диалог. 
    Обрабатывает дислокацию/терминал сразу ИЛИ запускает диалог для поезда.
    """
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message or not update.message.document:
        return ConversationHandler.END
    
    document = update.message.document
    original_filename = document.file_name
    
    if not original_filename or not original_filename.lower().endswith('.xlsx'):
        await update.message.reply_text("Пожалуйста, отправьте файл в формате .xlsx.")
        return ConversationHandler.END

    file_id = document.file_id
    dest_folder = DISLOCATION_DOWNLOAD_FOLDER 
    
    await update.message.reply_text(f"📥 Получен файл: **{original_filename}**", parse_mode='Markdown')
    
    dest_path = await save_temp_file_async(
        context.bot, 
        file_id, 
        original_filename, 
        dest_folder
    )
    
    if not dest_path:
        await notify_admin(f"❌ Ошибка: Не удалось скачать файл {original_filename}.", silent=False)
        return ConversationHandler.END

    filename_lower = original_filename.lower()

    # --- 1. Обработка файла дислокации (103) ---
    if filename_lower.startswith('103_'):
        logger.info(f"📥 [Admin Upload] Начало обработки файла дислокации: {original_filename}")
        try:
            processed_count = await process_dislocation_file(str(dest_path))
            await update.message.reply_text(f"✅ Обработка дислокации завершена. Обновлено записей: **{processed_count}**.", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла дислокации: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла дислокации: {e}")
        
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END

    # --- 2. Обработка отчета терминала (A-Terminal) ---
    elif re.search(TERMINAL_REPORT_PATTERN, original_filename, re.IGNORECASE):
        logger.info(f"📥 [Admin Upload] Начало обработки отчета терминала: {original_filename}")
        try:
            stats = await process_terminal_report_file(str(dest_path))
            await update.message.reply_text(
                f"✅ Отчет терминала **{original_filename}** обработан.\n"
                f"Контейнеров добавлено: **{stats.get('added', 0)}**\n"
                f"Обновлено: **{stats.get('updated', 0)}**",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке отчета терминала: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке отчета терминала: {e}")
            
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END
            
    # --- 3. Обработка файла поезда (KXX-YYY) ---
    elif extract_train_code_from_filename(original_filename):
        train_code = extract_train_code_from_filename(original_filename)
        logger.info(f"📥 [Admin Upload] Обнаружен файл поезда: {train_code}. Запускаю диалог перегруза.")
        
        # --- Сразу считаем контейнеры ---
        container_map = await _collect_containers_from_excel(str(dest_path))
        container_count = len(container_map)
        if container_count == 0:
             await update.message.reply_text(f"⚠️ В файле поезда {train_code} не найдено ни одного контейнера. Импорт отменен.")
             if os.path.exists(dest_path): os.remove(dest_path)
             return ConversationHandler.END
        # ---

        # Сохраняем данные для следующих шагов
        context.user_data['train_file_path'] = dest_path
        context.user_data['train_code'] = train_code
        context.user_data['admin_id'] = update.effective_user.id
        context.user_data['container_count'] = container_count # <--- Сохраняем кол-во

        keyboard = [
            [
                InlineKeyboardButton("✅ Да, с перегрузом", callback_data="overload_yes"),
                InlineKeyboardButton("❌ Нет, обычная загрузка", callback_data="overload_no")
            ]
        ]
        await update.message.reply_text(
            f"Поезд **{train_code}** ({container_count} конт.)\n\n"
            f"Этот поезд отправлен с перегрузом в пути следования?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return ASK_OVERLOAD_CONFIRM # Переходим в состояние ожидания ответа
            
    else:
        await update.message.reply_text("⚠️ Не удалось определить тип файла (103_, KXX-YYY, или A-Terminal).")
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END


async def handle_overload_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ответ (Да/Нет) на вопрос о перегрузе."""
    query = update.callback_query
    await query.answer()
    
    if not context.user_data or 'train_file_path' not in context.user_data:
        await query.edit_message_text("❌ Ошибка сессии. Пожалуйста, загрузите файл заново.")
        return ConversationHandler.END

    choice = query.data
    dest_path = context.user_data['train_file_path']
    train_code = context.user_data['train_code']
    admin_id = context.user_data['admin_id']
    container_count = context.user_data['container_count']
    
    if choice == "overload_no":
        logger.info(f"Выбрана обычная загрузка для поезда {train_code}")
        response_lines = []
        
        # 1. Запускаем обычный импорт (для TerminalContainer)
        try:
            updated_count, total_count, _ = await import_train_from_excel(str(dest_path))
            response_lines.append(
                f"✅ Обычный импорт в `TerminalContainer` завершен.\n"
                f"  (Обновлено/Найдено: **{updated_count}/{total_count}**)"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка импорта в `TerminalContainer`: {e}", exc_info=True)
            response_lines.append(f"❌ Ошибка импорта в `TerminalContainer`: {e}")

        # 2. Записываем в новую таблицу 'Train' (без перегруза)
        try:
            await upsert_train_on_upload(
                terminal_train_number=train_code, # <--- ✅ Используем правильное поле
                container_count=container_count,
                admin_id=admin_id,
                overload_station_name=None, # <--- Нет перегруза
                overload_date=None
            )
            response_lines.append(f"✅ Запись в таблице Поездов (`Train`) для **{train_code}** создана/обновлена.")
        except Exception as e:
            logger.error(f"❌ Ошибка записи в таблицу `Train`: {e}", exc_info=True)
            response_lines.append(f"❌ Ошибка записи в таблицу `Train`: {e}")
            
        await query.edit_message_text("\n\n".join(response_lines), parse_mode='Markdown')
        
        if os.path.exists(dest_path): os.remove(dest_path)
        context.user_data.clear()
        return ConversationHandler.END
        
    elif choice == "overload_yes":
        # --- ПЕРЕХОД К ВВОДУ СТАНЦИИ ---
        logger.info(f"Поезд {train_code} помечен как 'с перегрузом'. Запрашиваю станцию.")
        await query.edit_message_text(
            f"Поезд **{train_code}**.\n\n"
            f"Пожалуйста, введите **название станции перегруза**:"
            f"\n(Или /cancel для отмены)",
            parse_mode='Markdown'
        )
        return ASK_STATION_NAME

    # Добавляем возврат для случая, если choice не "yes" или "no" (хотя pattern это исключает)
    return ConversationHandler.END


async def handle_overload_station_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию, выполняет оба импорта и завершает диалог."""
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END
        
    station_name = update.message.text.strip()
    
    dest_path = context.user_data['train_file_path']
    train_code = context.user_data['train_code']
    admin_id = context.user_data['admin_id']
    container_count = context.user_data['container_count']

    response_lines = []

    # 1. Сначала выполняем обычный импорт (для TerminalContainer)
    try:
        updated_count, total_count, _ = await import_train_from_excel(str(dest_path))
        response_lines.append(
            f"✅ Обычный импорт в `TerminalContainer` завершен.\n"
            f"  (Обновлено/Найдено: **{updated_count}/{total_count}**)"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка импорта в `TerminalContainer`: {e}", exc_info=True)
        response_lines.append(f"❌ Ошибка импорта в `TerminalContainer`: {e}")

    # 2. Логируем событие перегруза в 'Train'
    try:
        success = await upsert_train_on_upload(
            terminal_train_number=train_code, # <--- ✅ Используем правильное поле
            container_count=container_count,
            admin_id=admin_id,
            overload_station_name=station_name, # <--- Станция указана
            overload_date=datetime.now() # <--- Ставим текущую дату
        )
        if success:
            response_lines.append(
                f"✅ Событие перегруза поезда **{train_code}** на станции **{station_name}** "
                f"успешно зарегистрировано в таблице `Train`."
            )
        else:
            response_lines.append(f"❌ Не удалось зарегистрировать событие перегруза в `Train`.")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка логирования перегруза в `Train`: {e}", exc_info=True)
        response_lines.append(f"❌ Критическая ошибка логирования перегруза в `Train`: {e}")

    # Отправляем сводный отчет
    await update.message.reply_text("\n\n".join(response_lines), parse_mode='Markdown')
    
    if os.path.exists(dest_path): os.remove(dest_path)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_overload_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог и удаляет временный файл."""
    if context.user_data:
        dest_path = context.user_data.get('train_file_path')
        if dest_path and os.path.exists(dest_path):
            os.remove(dest_path)
        context.user_data.clear()
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Загрузка отменена.")
    elif update.message:
        await update.message.reply_text("❌ Загрузка отменена.")
        
    return ConversationHandler.END


def get_admin_upload_conversation_handler():
    """Возвращает ConversationHandler для загрузки файлов."""
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Chat(ADMIN_CHAT_ID) & filters.Document.FileExtension("xlsx"), 
                handle_admin_document_entry
            )
        ],
        states={
            ASK_OVERLOAD_CONFIRM: [
                CallbackQueryHandler(handle_overload_confirm, pattern="^overload_(yes|no)$")
            ],
            ASK_STATION_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_overload_station_name)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_overload_dialog)],
    )