# handlers/admin/uploads.py
import os
import re
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_CHAT_ID
from logger import get_logger
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_DIR as DISLOCATION_DOWNLOAD_FOLDER 
from services.terminal_importer import import_train_from_excel, extract_train_code_from_filename, process_terminal_report_file
from services.file_utils import save_temp_file_async
from utils.notify import notify_admin

logger = get_logger(__name__)

# ✅ ШАБЛОН ДЛЯ ОТЧЕТА ТЕРМИНАЛА
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
        "   - Имя файла должно содержать `A-Terminal` (например, `A-Terminal 21.10.2025.xlsx`).\n\n"
        "Отправьте Excel-файл как документ (не как фото)."
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def handle_admin_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает загруженные администратором файлы Excel."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message or not update.message.document:
        return
    
    document = update.message.document
    original_filename = document.file_name
    
    if not original_filename or not original_filename.lower().endswith('.xlsx'):
        await update.message.reply_text("Пожалуйста, отправьте файл в формате .xlsx.")
        return

    file_id = document.file_id
    
    # Сохранение файла во временную папку
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
        return

    # --- Определение типа файла и обработка ---

    filename_lower = original_filename.lower()
    success = False
    
    # 1. Проверка: Файл дислокации (103)?
    if filename_lower.startswith('103_'):
        logger.info(f"📥 [Admin Upload] Начало обработки файла дислокации: {original_filename}")
        try:
            processed_count = await process_dislocation_file(str(dest_path))
            await update.message.reply_text(f"✅ Обработка дислокации завершена. Обновлено записей: **{processed_count}**.", parse_mode='Markdown')
            success = True
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла дислокации: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла дислокации: {e}")
            
    # 2. Проверка: Отчет терминала (A-Terminal)?
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
            success = True
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке отчета терминала: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке отчета терминала: {e}")
            
    # 3. Проверка: Файл поезда (KXX-YYY)?
    elif extract_train_code_from_filename(original_filename):
        train_code = extract_train_code_from_filename(original_filename)
        logger.info(f"📥 [Admin Upload] Начало обработки файла поезда: {train_code}")
        
        try:
            # NOTE: Импорт поезда сработает ТОЛЬКО, если контейнеры уже есть в TerminalContainer!
            updated_count, total_count, _ = await import_train_from_excel(str(dest_path))
            
            await update.message.reply_text(
                f"✅ Импорт поезда **{train_code}** завершен.\n"
                f"Найдено контейнеров в файле: **{total_count}**\n"
                f"Обновлено контейнеров в базе: **{updated_count}**",
                parse_mode='Markdown'
            )
            success = True
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла поезда: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла поезда: {e}")
            
    else:
        await update.message.reply_text("⚠️ Не удалось определить тип файла (дислокация 103_, поезд KXX-YYY, или отчет A-Terminal).")
        
    # Удаляем временный файл
    if os.path.exists(dest_path):
        os.remove(dest_path)