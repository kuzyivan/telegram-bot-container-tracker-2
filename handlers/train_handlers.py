# handlers/train_handlers.py
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from logger import get_logger
from config import ADMIN_CHAT_ID
from services.train_importer import import_train_from_excel

logger = get_logger(__name__)

DOWNLOAD_DIR = Path("/root/AtermTrackBot/download_train")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# /upload_train как явная команда (опционально)
async def upload_train_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "Отправьте сюда Excel-файл вида 'КП К25-073 Селятино.xlsx'. "
        "Бот возьмёт «К25-073» из имени и проставит его в столбец «train» "
        "для всех контейнеров, найденных в файле."
    )

# обработчик документов (xlsx)
async def handle_train_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        # игнорим чужих
        return

    doc = update.message.document if update.message else None
    if not doc:
        return

    # допустим только XLSX
    filename = doc.file_name or "train.xlsx"
    if not filename.lower().endswith(".xlsx"):
        await update.message.reply_text("⛔ Пришлите Excel-файл .xlsx")
        return

    # скачиваем
    file = await context.bot.get_file(doc.file_id)
    dest = DOWNLOAD_DIR / filename
    await file.download_to_drive(custom_path=str(dest))
    logger.info(f"📥 Получен файл от админа: {dest}")

    # импорт
    try:
        updated, train_code = await import_train_from_excel(dest)
        await update.message.reply_text(
            f"✅ Поезд <b>{train_code}</b> обработан.\n"
            f"Обновлено контейнеров: <b>{updated}</b>.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Ошибка импорта поезда из файла")
        await update.message.reply_text(f"❌ Ошибка: {e}")