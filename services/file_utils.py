# services/file_utils.py
import os
import asyncio
from telegram import Bot
from logger import get_logger

logger = get_logger(__name__)

async def save_temp_file_async(bot: Bot, file_id: str, filename: str, destination_folder: str) -> str | None:
    """
    Загружает файл по file_id и сохраняет его во временную папку.
    Возвращает полный путь к сохраненному файлу.
    """
    try:
        # Получаем объект файла Telegram
        file = await bot.get_file(file_id)
        
        # Создаем папку, если она не существует
        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
            
        # Формируем путь сохранения
        destination_path = os.path.join(destination_folder, filename)
        
        # Асинхронно скачиваем файл
        await file.download_to_drive(custom_path=destination_path)
        
        logger.info(f"[FileUtils] Файл {filename} успешно сохранен в {destination_path}")
        return destination_path
        
    except Exception as e:
        logger.error(f"[FileUtils] Не удалось сохранить файл {filename}: {e}", exc_info=True)
        return None