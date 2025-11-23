# services/imap_service.py

import os
import re
import time  # <--- ДОБАВЛЕНО для пауз между попытками
from typing import Optional, Union, Iterator
from contextlib import contextmanager

# Импорты из imap-tools
from imap_tools.mailbox import MailBox, BaseMailBox
from imap_tools.query import A, AND

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
        if not all([EMAIL, PASSWORD, IMAP_SERVER]):
            logger.error("[ImapService] EMAIL, PASSWORD или IMAP_SERVER не заданы в .env.")
            yield None
            return

        mailbox = None
        is_connected = False
        
        # --- НАСТРОЙКИ RETRY ---
        max_retries = 3
        retry_delay = 5  # секунд
        # -----------------------

        for attempt in range(1, max_retries + 1):
            try:
                assert EMAIL and PASSWORD
                
                logger.info(f"[ImapService] Попытка подключения {attempt}/{max_retries} к {IMAP_SERVER}...")
                
                # Устанавливаем явный тайм-аут 60 секунд (по умолчанию может быть меньше)
                mailbox = MailBox(IMAP_SERVER, timeout=60)
                
                mailbox.login(EMAIL, PASSWORD) 
                is_connected = True
                logger.info(f"🟢 [ImapService] Успешный login.")
                
                mailbox.folder.set("INBOX")  
                logger.info(f"🟢 [ImapService] Успешно выбрана папка 'INBOX'.")
                
                # Если успешно подключились — прерываем цикл попыток
                break
            
            except Exception as e:
                logger.warning(f"⚠️ [ImapService] Ошибка подключения (попытка {attempt}): {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    logger.error(f"❌ [ImapService] Не удалось подключиться после {max_retries} попыток: {e}", exc_info=True)
                    yield None
                    return

        # Если вышли из цикла и подключены
        if is_connected and mailbox:
            try:
                yield mailbox
            except Exception as e:
                logger.error(f"❌ [ImapService] Ошибка во время работы с ящиком: {e}", exc_info=True)
                yield None
            finally:
                try:
                    mailbox.logout()
                    logger.info(f"🟢 [ImapService] Logout выполнен.")
                except Exception as e:
                     logger.warning(f"⚠️ [ImapService] Ошибка при попытке logout: {e}. Считаем, что соединение закрыто.")
                     pass
        else:
            # Этот блок выполнится, если цикл завершился без успеха (хотя yield None выше уже сработал)
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
                        # Снижаем уровень лога до debug, чтобы не спамить
                        # logger.debug(f"⚠️ [ImapService] Письмо '{msg.subject}' пропущено: не соответствует шаблону.")
                        continue
                        
                    logger.info(f"🟢 [ImapService] Найдено письмо: '{msg.subject}' от {msg.date.strftime('%a, %d %b %Y %H:%M:%S %z')}")
                    
                    # 4. Поиск вложений
                    for att in msg.attachments:
                        
                        if re.search(filename_pattern, att.filename, re.IGNORECASE):
                            
                            # 5. Сохранение файла
                            filepath = os.path.join(DOWNLOAD_DIR, att.filename)
                            
                            logger.info(f"🟢 [ImapService] Вложение '{att.filename}' сохраняется в {filepath}")
                            
                            with open(filepath, 'wb') as f:
                                f.write(att.payload)
                                
                            logger.info(f"✅ [ImapService] Вложение '{att.filename}' успешно сохранено.")

                            # 6. Пометка письма как прочитанного.
                            mailbox.flag([msg.uid], 'SEEN', value=True) 
                            
                            return filepath
                            
                    logger.info(f"⚠️ [ImapService] Письмо '{msg.subject}' пропущено: нет подходящих вложений.")

                logger.info(f"❌ [ImapService] Не найдено ни одного подходящего вложения за последние 50 писем.")
                return None

            except Exception as e:
                logger.error(f"❌ [ImapService] Ошибка при скачивании вложений: {e}", exc_info=True)
                return None