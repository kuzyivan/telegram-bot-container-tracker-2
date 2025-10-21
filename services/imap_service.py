# services/imap_service.py

import os
import re
import datetime
from typing import Optional, Union, Iterator
from contextlib import contextmanager

# ✅ ИСПРАВЛЕНИЕ ИМПОРТОВ: Импортируем из конкретных подмодулей
from imap_tools.mailbox import MailBox, BaseMailBox # MailBox, BaseMailBox
from imap_tools.query import A, AND               # A, AND

from logger import get_logger

logger = get_logger(__name__)

# Используем существующие имена переменных EMAIL и PASSWORD из вашего .env
EMAIL = os.getenv("EMAIL")          
PASSWORD = os.getenv("PASSWORD")    
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.yandex.ru") 
DOWNLOAD_DIR = 'downloads' 

class ImapService:
    """Сервис для работы с IMAP (почтой) для скачивания вложений."""

    def __init__(self):
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)

    @contextmanager
    def _connect(self) -> Iterator[Optional[MailBox]]:
        # ... (код подключения _connect остается прежним) ...
        if not all([EMAIL, PASSWORD, IMAP_SERVER]):
            logger.error("[ImapService] EMAIL, PASSWORD или IMAP_SERVER не заданы в .env.")
            yield None
            return

        mailbox = MailBox(IMAP_SERVER)
        is_connected = False
        try:
            assert EMAIL and PASSWORD
            
            logger.info(f"[ImapService] Попытка подключения к {IMAP_SERVER} для {EMAIL}...")
            
            mailbox.login(EMAIL, PASSWORD) 
            is_connected = True
            logger.info(f"🟢 [ImapService] Успешный login.")
            
            mailbox.folder.set("INBOX")  
            logger.info(f"🟢 [ImapService] Успешно выбрана папка 'INBOX'.")
            
            yield mailbox
            
        except Exception as e:
            logger.error(f"❌ [ImapService] Ошибка подключения к IMAP или выбора папки 'INBOX': {e}", exc_info=True)
            yield None
        finally:
            if is_connected:
                try:
                    # ✅ ИСПРАВЛЕНИЕ: Мы знаем, что msg.uid всегда str, если письмо найдено.
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
                # 1. Формирование критерия поиска IMAP
                criteria_list = [A(from_=sender_filter, seen=False), A(all=True)]
                
                # 2. Поиск писем
                emails = mailbox.fetch(
                    criteria=AND(*criteria_list), 
                    bulk=True, 
                    reverse=True, 
                    limit=50,
                    charset='utf8' 
                )
                
                # 3. Итерация и ФИЛЬТРАЦИЯ REGEX В PYTHON
                for msg in emails:
                    
                    # Фильтруем по регулярному выражению в теме
                    if not re.search(subject_filter, msg.subject, re.IGNORECASE):
                        logger.info(f"⚠️ [ImapService] Письмо '{msg.subject}' пропущено: не соответствует REGEX шаблону темы.")
                        continue
                        
                    logger.info(f"🟢 [ImapService] Найдено письмо: '{msg.subject}' от {msg.date.strftime('%a, %d %b %Y %H:%M:%S %z')}")
                    
                    # 4. Поиск вложений
                    for att in msg.attachments:
                        if re.match(filename_pattern, att.filename, re.IGNORECASE):
                            
                            # 5. Сохранение файла
                            filepath = os.path.join(DOWNLOAD_DIR, att.filename)
                            
                            logger.info(f"🟢 [ImapService] Вложение '{att.filename}' сохраняется в {filepath}")
                            
                            with open(filepath, 'wb') as f:
                                f.write(att.payload)
                                
                            logger.info(f"✅ [ImapService] Вложение '{att.filename}' успешно сохранено.")

                            # 6. Пометка письма как прочитанного.
                            # msg.uid всегда str, если письмо найдено, поэтому Pylance ошибается
                            # Но для устранения предупреждения, обернем uid в tuple/list
                            mailbox.flag([msg.uid], 'SEEN', value=True) 
                            
                            return filepath
                            
                    logger.info(f"⚠️ [ImapService] Письмо '{msg.subject}' пропущено: нет подходящих вложений.")

                logger.info(f"❌ [ImapService] Не найдено ни одного подходящего вложения за последние 50 писем.")
                return None

            except Exception as e:
                logger.error(f"❌ [ImapService] Ошибка при скачивании вложений: {e}", exc_info=True)
                return None