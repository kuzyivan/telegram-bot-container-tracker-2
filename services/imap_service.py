# services/imap_service.py
import os
from contextlib import contextmanager
# ИСПРАВЛЕНИЕ 1: Импортируем 'Iterator' и 'BaseMailBox' для самой точной типизации
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
    # ИСПРАВЛЕНИЕ 2: Используем Iterator[Union[BaseMailBox, None]]
    # Это точно соответствует тому, что ожидает декоратор @contextmanager
    # и что возвращает библиотека imap-tools (базовый класс BaseMailBox).
    def _connect(self) -> Iterator[Union[BaseMailBox, None]]:
        """
        Приватный метод-контекстный менеджер для безопасного подключения к почтовому ящику.
        """
        if not all([EMAIL, PASSWORD, IMAP_SERVER]):
            logger.error("[ImapService] EMAIL, PASSWORD или IMAP_SERVER не заданы в .env.")
            yield None
            return

        try:
            assert EMAIL and PASSWORD
            with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder="INBOX") as mailbox:
                logger.info(f"[ImapService] Успешное подключение к {IMAP_SERVER} для пользователя {EMAIL}.")
                yield mailbox
        except Exception as e:
            logger.error(f"[ImapService] Ошибка подключения к IMAP: {e}", exc_info=True)
            yield None

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

            messages = mailbox.fetch(criteria, reverse=True)
            try:
                message: Union[MailMessage, None] = next(messages, None)
                if not message:
                    logger.info(f"[ImapService] Писем по критерию не найдено.")
                    return None

                logger.info(f"[ImapService] Найдено письмо: '{message.subject}' от {message.date_str}")
                for att in message.attachments:
                    if att.filename and att.filename.lower().endswith(file_extension):
                        os.makedirs(download_folder, exist_ok=True)
                        save_path = os.path.join(download_folder, att.filename)
                        with open(save_path, "wb") as f:
                            f.write(att.payload)
                        logger.info(f"[ImapService] Вложение '{att.filename}' сохранено в {save_path}")
                        return save_path

                logger.warning(f"[ImapService] В письме нет вложений с расширением '{file_extension}'.")
                return None
            except Exception as e:
                logger.error(f"[ImapService] Ошибка при обработке писем: {e}", exc_info=True)
                return None