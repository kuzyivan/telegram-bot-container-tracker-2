# handlers/admin/uploads.py
from telegram import Update
from telegram.ext import ContextTypes
import os
from pathlib import Path

from .utils import admin_only_handler # ✅ ИЗМЕНЕНИЕ ЗДЕСЬ
from logger import get_logger
from services.train_importer import import_train_from_excel, extract_train_code_from_filename
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_FOLDER as DISLOCATION_DOWNLOAD_FOLDER

logger = get_logger(__name__)

def is_dislocation_file(filename: str) -> bool:
    """Проверяет, начинается ли имя файла с префикса '103_'."""
    return os.path.basename(filename).strip().startswith("103_")

async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инструкция по ручной загрузке файлов."""
    if not await admin_only_handler(update, context):
        return
    
    await update.message.reply_text(
        "Отправьте Excel-файл (.xlsx) для обновления данных:\n\n"
        "📄 **Файл дислокации**: Имя файла должно начинаться с `103_`.\n\n"
        "🚆 **Файл поезда**: Имя файла должно содержать номер вида `К25-073`.",
        parse_mode="Markdown"
    )

async def handle_admin_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый обработчик для Excel-файлов от администратора."""
    if not await admin_only_handler(update, context) or not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = (doc.file_name or "unknown.xlsx").strip()
    
    if not filename.lower().endswith(".xlsx"):
        await update.message.reply_text("⛔ Пришлите Excel-файл в формате .xlsx")
        return

    os.makedirs(DISLOCATION_DOWNLOAD_FOLDER, exist_ok=True)
    dest_path = Path(DISLOCATION_DOWNLOAD_FOLDER) / filename
    
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(custom_path=str(dest_path))
    logger.info(f"📥 [Admin Upload] Получен файл: {filename}")

    try:
        if extract_train_code_from_filename(filename):
            logger.info(f"[Admin Upload] Файл '{filename}' определен как файл поезда.")
            updated, total, train_code = await import_train_from_excel(str(dest_path))
            text = (f"✅ Поезд <b>{train_code}</b> обработан.\n"
                    f"Обновлено: <b>{updated}</b> из <b>{total}</b>.")
            await update.message.reply_html(text)

        elif is_dislocation_file(filename):
            logger.info(f"[Admin Upload] Файл '{filename}' определен как файл дислокации.")
            processed_count = await process_dislocation_file(str(dest_path))
            text = (f"✅ База дислокации обновлена.\n"
                    f"Обработано записей: <b>{processed_count}</b>.")
            await update.message.reply_html(text)

        else:
            logger.warning(f"[Admin Upload] Отклонено: '{filename}' не соответствует правилам.")
            await update.message.reply_markdown_v2(
                "❌ *Не удалось определить тип файла*\n\n"
                "Проверьте имя:\n"
                "• `103_` для дислокации\n"
                "• `К25\\-073` для поезда"
            )
            
    except Exception as e:
        logger.exception(f"[Admin Upload] Ошибка при обработке файла '{filename}'")
        await update.message.reply_text(f"❌ Ошибка: {e}")