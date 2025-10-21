# handlers/admin/uploads.py
import os
import re
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_CHAT_ID
from logger import get_logger
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_DIR as DISLOCATION_DOWNLOAD_FOLDER # ✅ ИСПРАВЛЕНО: DOWNLOAD_DIR
from services.train_importer import import_train_from_excel, extract_train_code_from_filename
from services.file_utils import save_temp_file_async
from utils.notify import notify_admin

logger = get_logger(__name__)

async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информирует администратора о способе загрузки файлов."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message:
        return

    text = (
        "**Инструкция по загрузке файлов:**\n\n"
        "1. **Файлы дислокации (103):**\n"
        "   - Имя файла должно начинаться с `103_` (например, `103_20251021.xlsx`).\n"
        "   - Будет запущен процесс обновления дислокации.\n\n"
        "2. **Файлы поездов (KXX-YYY):**\n"
        "   - Имя файла должно содержать код поезда (например, `КП К25-073 Селятино.xlsx`).\n"
        "   - Будет запущен процесс привязки контейнеров к поезду.\n\n"
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
    dest_folder = DISLOCATION_DOWNLOAD_FOLDER # Используем DISLOCATION_DOWNLOAD_FOLDER
    
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

    # Проверка: Файл дислокации?
    if original_filename.lower().startswith('103_'):
        logger.info(f"📥 [Admin Upload] Получен файл: {original_filename}")
        logger.info(f"[Admin Upload] Файл '{original_filename}' определен как файл дислокации.")
        
        try:
            processed_count = await process_dislocation_file(str(dest_path))
            await update.message.reply_text(f"✅ Обработка завершена. Обновлено записей дислокации: **{processed_count}**.", parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла '{original_filename}'", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла дислокации: {e}")
            
    # Проверка: Файл поезда?
    elif extract_train_code_from_filename(original_filename):
        train_code = extract_train_code_from_filename(original_filename)
        logger.info(f"📥 [Admin Upload] Получен файл: {original_filename}. Определен код поезда: {train_code}")
        
        try:
            updated_count, total_count, _ = await import_train_from_excel(str(dest_path))
            
            await update.message.reply_text(
                f"✅ Импорт поезда **{train_code}** завершен.\n"
                f"Найдено контейнеров в файле: **{total_count}**\n"
                f"Обновлено контейнеров в базе: **{updated_count}**",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла поезда '{original_filename}'", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла поезда: {e}")
            
    else:
        await update.message.reply_text("⚠️ Не удалось определить тип файла (дислокация 103_ или поезд KXX-YYY).")
        
    # Удаляем временный файл
    if os.path.exists(dest_path):
        os.remove(dest_path)