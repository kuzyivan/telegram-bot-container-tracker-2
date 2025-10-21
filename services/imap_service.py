# services/imap_service.py
import os
from contextlib import contextmanager
from typing import Iterator, Union, Any
from imap_tools.mailbox import MailBox, BaseMailBox
from imap_tools.message import MailMessage
from logger import get_logger

logger = get_logger(__name__)

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.yandex.ru")


class ImapService:
    """
    Сервис для инкапсуляции работы с почтовым ящиком по протоколу IMAP.
    """

    @contextmanager
    def _connect(self) -> Iterator[Union[BaseMailBox, None]]:
        """
        Приватный метод-контекстный менеджер для безопасного подключения к почтовому ящику.
        """
        if not all([EMAIL, PASSWORD, IMAP_SERVER]):
            # ✅ ЛОГИРОВАНИЕ: Критическая ошибка конфигурации
            logger.error("[ImapService] EMAIL, PASSWORD или IMAP_SERVER не заданы в .env.")
            yield None
            return

        mailbox = MailBox(IMAP_SERVER)
        try:
            assert EMAIL and PASSWORD
            
            # ✅ ЛОГИРОВАНИЕ: Начало подключения
            logger.info(f"[ImapService] Попытка подключения к {IMAP_SERVER} для {EMAIL}...")
            
            # Шаг 1: Логин (переводит состояние в AUTH)
            mailbox.login(EMAIL, PASSWORD) 
            logger.info(f"🟢 [ImapService] Успешный login.")
            
            # Шаг 2: Выбор папки (переводит состояние в SELECTED)
            mailbox.folder.set("INBOX")  
            logger.info(f"🟢 [ImapService] Успешно выбрана папка 'INBOX'.")
            
            yield mailbox
            
        except Exception as e:
            # ✅ ЛОГИРОВАНИЕ: Ошибка подключения/выбора папки
            logger.error(f"❌ [ImapService] Ошибка подключения к IMAP или выбора папки 'INBOX': {e}", exc_info=True)
            yield None
        finally:
            if mailbox.is_logged_in:
                mailbox.logout()
                # ✅ ЛОГИРОВАНИЕ: Выход
                logger.info(f"🟢 [ImapService] Logout выполнен.")

    def download_latest_attachment(
        self,
        criteria: Any,
        download_folder: str,
        file_extension: str = ".xlsx"
    ) -> Union[str, None]:
        """
        Находит самое свежее письмо, скачивает вложение и возвращает путь к файлу.
        """
        with self._connect() as mailbox:
            if not mailbox:
                return None

            # ✅ ЛОГИРОВАНИЕ: Начало поиска писем
            logger.info(f"[ImapService] Поиск писем по критериям: {criteria}...")
            
            messages = mailbox.fetch(criteria, reverse=True)
            try:
                message: Union[MailMessage, None] = next(messages, None)
                if not message:
                    logger.info(f"❌ [ImapService] Писем по критерию не найдено.")
                    return None

                # ✅ ЛОГИРОВАНИЕ: Найденное письмо
                logger.info(f"🟢 [ImapService] Найдено письмо: '{message.subject}' от {message.date_str}")
                
                for att in message.attachments:
                    if att.filename and att.filename.lower().endswith(file_extension):
                        os.makedirs(download_folder, exist_ok=True)
                        save_path = os.path.join(download_folder, att.filename)
                        
                        # ✅ ЛОГИРОВАНИЕ: Сохранение файла
                        logger.info(f"🟢 [ImapService] Вложение '{att.filename}' сохраняется в {save_path}")
                        
                        with open(save_path, "wb") as f:
                            f.write(att.payload)
                        logger.info(f"✅ [ImapService] Вложение '{att.filename}' успешно сохранено.")
                        return save_path

                logger.warning(f"❌ [ImapService] В письме нет вложений с расширением '{file_extension}'.")
                return None
            except Exception as e:
                # ✅ ЛОГИРОВАНИЕ: Ошибка обработки
                logger.error(f"❌ [ImapService] Ошибка при обработке писем: {e}", exc_info=True)
                return None