# handlers/train_handlers.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple, Any

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

from logger import get_logger
from config import ADMIN_CHAT_ID
from services.train_importer import import_train_from_excel

logger = get_logger(__name__)

# Папка для ручной загрузки файлов поездов
DOWNLOAD_DIR = Path("/root/AtermTrackBot/download_train")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# /upload_train — подсказка по загрузке
async def upload_train_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "Отправьте сюда Excel-файл вида 'КП К25-073 Селятино.xlsx'. "
        "Бот возьмёт «К25-073» из имени и проставит его в столбец «train» "
        "для всех контейнеров, найденных в файле."
    )


# Основной обработчик документов (xlsx)
async def handle_train_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_CHAT_ID:
        # игнорируем не-админа
        return

    if not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = (doc.file_name or "train.xlsx").strip()

    # допускаем только .xlsx
    if not filename.lower().endswith(".xlsx"):
        await update.message.reply_text("⛔ Пришлите Excel-файл .xlsx")
        return

    # скачиваем файл на диск
    file = await context.bot.get_file(doc.file_id)
    dest = DOWNLOAD_DIR / filename
    await file.download_to_drive(custom_path=str(dest))
    logger.info(f"📥 Получен файл от админа: {dest}")

    # вызываем импортёр поездов
    try:
        result: Any = await import_train_from_excel(dest)
        # Поддерживаем обе сигнатуры: (updated, train_code) ИЛИ (updated, total, train_code)
        updated: int = 0
        total: int | None = None
        train_code: str = "—"

        if isinstance(result, tuple):
            if len(result) == 3:
                updated, total, train_code = result  # type: ignore[misc]
            elif len(result) == 2:
                updated, train_code = result  # type: ignore[misc]
            else:
                # непредвиденная форма
                logger.warning(f"import_train_from_excel() вернул необычный результат: {result}")
        else:
            logger.warning(f"import_train_from_excel() вернул не-кортеж: {type(result)}")

        # Формируем ответ
        if total is not None:
            text = (
                f"✅ Поезд <b>{train_code}</b> обработан.\n"
                f"Обновлено контейнеров: <b>{updated}</b> из <b>{total}</b>."
            )
        else:
            text = (
                f"✅ Поезд <b>{train_code}</b> обработан.\n"
                f"Обновлено контейнеров: <b>{updated}</b>."
            )

        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Ошибка импорта поезда из файла")
        await update.message.reply_text(f"❌ Ошибка: {e}")


# Регистрация хендлеров в приложении

def register_train_handlers(app: Application) -> None:
    """Подключить хендлеры загрузки поездов к приложению PTB."""
    # Команда-подсказка только для админа
    app.add_handler(CommandHandler("upload_train", upload_train_help))

    # Приём Excel-документов (xlsx) от админа
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_CHAT_ID)
            & filters.Document.MimeType(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            handle_train_excel,
        )
    )

    # Про запас — если Telegram не прислал MIME-тип, проверим по расширению
    app.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_CHAT_ID)
            & filters.Document.FileExtension("xlsx"),
            handle_train_excel,
        )
    )