# services/imap_service.py

import os
import re
import datetime
from typing import Optional, Union, Iterator
from contextlib import contextmanager

from imap_tools import MailBox, BaseMailBox, A
from logger import get_logger

logger = get_logger(__name__)

# ✅ ИСПРАВЛЕНИЕ ПЕРЕМЕННЫХ: Используем существующие имена EMAIL и PASSWORD из вашего .env
EMAIL = os.getenv("EMAIL")          
PASSWORD = os.getenv("PASSWORD")    
# Устанавливаем значение по умолчанию для IMAP_SERVER
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.yandex.ru") 
DOWNLOAD_DIR = 'downloads' 

class ImapService:
    """Сервис для работы с IMAP (почтой) для скачивания вложений."""

    def __init__(self):
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)

    @contextmanager
    def _connect(self) -> Iterator[Optional[MailBox]]:
        """
        Приватный метод-контекстный менеджер для безопасного подключения к почтовому ящику.
        """
        if not all([EMAIL, PASSWORD, IMAP_SERVER]):
            logger.error("[ImapService] EMAIL, PASSWORD или IMAP_SERVER не заданы в .env.")
            yield None
            return

        mailbox = MailBox(IMAP_SERVER)
        is_connected = False
        try:
            assert EMAIL and PASSWORD
            
            logger.info(f"[ImapService] Попытка подключения к {IMAP_SERVER} для {EMAIL}...")
            
            # Шаг 1: Логин
            mailbox.login(EMAIL, PASSWORD) 
            is_connected = True
            logger.info(f"🟢 [ImapService] Успешный login.")
            
            # Шаг 2: Выбор папки
            mailbox.folder.set("INBOX")  
            logger.info(f"🟢 [ImapService] Успешно выбрана папка 'INBOX'.")
            
            yield mailbox
            
        except Exception as e:
            logger.error(f"❌ [ImapService] Ошибка подключения к IMAP или выбора папки 'INBOX': {e}", exc_info=True)
            yield None
        finally:
            # Пытаемся разлогиниться, только если логин был успешен.
            if is_connected:
                try:
                    mailbox.logout()
                    logger.info(f"🟢 [ImapService] Logout выполнен.")
                except Exception as e:
                     logger.warning(f"⚠️ [ImapService] Ошибка при попытке logout: {e}. Считаем, что соединение закрыто.")
                     pass


    def download_latest_attachment(self, subject_filter: str, sender_filter: str, filename_pattern: str) -> Optional[str]:
        """
        Скачивает самое свежее вложение, соответствующее критериям.
        Возвращает полный путь к скачанному файлу.
        """
        logger.info(f"[ImapService] Поиск писем по критериям: SUBJECT='{subject_filter}', SENDER='{sender_filter}'...")

        with self._connect() as mailbox:
            if mailbox is None:
                return None

            try:
                # 1. Поиск писем
                # ✅ ИСПРАВЛЕНИЕ КОДИРОВКИ: Добавляем charset='utf8' для поиска кириллицы
                emails = mailbox.fetch(
                    criteria=A(all=True, subject=subject_filter, from_=sender_filter, seen=False), 
                    bulk=True, 
                    reverse=True, 
                    limit=50,
                    charset='utf8' # <-- Устраняет UnicodeEncodeError
                )
                
                # 2. Итерация по письмам
                for msg in emails:
                    logger.info(f"🟢 [ImapService] Найдено письмо: '{msg.subject}' от {msg.date.strftime('%a, %d %b %Y %H:%M:%S %z')}")
                    
                    # 3. Поиск вложений
                    for att in msg.attachments:
                        if re.match(filename_pattern, att.filename, re.IGNORECASE):
                            
                            # 4. Сохранение файла
                            filepath = os.path.join(DOWNLOAD_DIR, att.filename)
                            
                            logger.info(f"🟢 [ImapService] Вложение '{att.filename}' сохраняется в {filepath}")
                            
                            with open(filepath, 'wb') as f:
                                f.write(att.payload)
                                
                            logger.info(f"✅ [ImapService] Вложение '{att.filename}' успешно сохранено.")

                            # 5. Пометка письма как прочитанного.
                            mailbox.flag(msg.uid, 'SEEN', value=True)
                            
                            return filepath
                            
                    logger.info(f"⚠️ [ImapService] Письмо '{msg.subject}' пропущено: нет подходящих вложений.")

                logger.info(f"❌ [ImapService] Не найдено ни одного подходящего вложения за последние 50 писем.")
                return None

            except Exception as e:
                logger.error(f"❌ [ImapService] Ошибка при скачивании вложений: {e}", exc_info=True)
                return None