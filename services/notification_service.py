# services/notification_service.py
import asyncio
from datetime import time
from telegram import Bot
from telegram.error import TimedOut, NetworkError

import config
from logger import get_logger
from queries.notification_queries import (
    get_subscriptions_for_time,
    get_tracking_data_for_containers,
    get_user_for_email,
)
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email

logger = get_logger(__name__)

class NotificationService:
    """
    Сервис, отвечающий за формирование и отправку отчетов о дислокации
    пользователям по расписанию.
    """
    def __init__(self, bot: Bot):
        """
        Инициализирует сервис с объектом бота для отправки сообщений.
        """
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time):
        """
        Главный метод. Получает все подписки на указанное время и запускает
        параллельную обработку для каждой из них.
        """
        subscriptions = await get_subscriptions_for_time(target_time)
        logger.info(f"Найдено {len(subscriptions)} подписок для рассылки в {target_time.strftime('%H:%M')}.")

        # Создаем и запускаем асинхронные задачи для каждого подписчика
        tasks = [self._process_single_subscription(sub) for sub in subscriptions]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_single_subscription(self, subscription):
        """
        Обрабатывает одну подписку: получает данные, создает отчет и отправляет его.
        """
        user_id = subscription.user_id
        containers = list(subscription.containers)
        logger.info(f"Обработка подписки для пользователя {user_id} на контейнеры: {containers}")

        report_data = await get_tracking_data_for_containers(containers)

        if not report_data:
            try:
                await self.bot.send_message(user_id, f"📝 Нет данных по отслеживаемым контейнерам: {', '.join(containers)}")
                logger.warning(f"Нет данных для пользователя {user_id}. Отправлено текстовое уведомление.")
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id} об отсутствии данных: {e}")
            return

        # Создаем Excel-файл. Эта функция может быть блокирующей, поэтому
        # запускаем ее в отдельном потоке, чтобы не блокировать asyncio.
        file_path = await asyncio.to_thread(create_excel_file, report_data, config.TRACKING_REPORT_COLUMNS)
        filename = get_vladivostok_filename()

        # Отправляем отчеты параллельно в Telegram и на почту
        await asyncio.gather(
            self._send_telegram_report_with_retry(user_id, file_path, filename),
            self._send_email_report_if_enabled(user_id, file_path)
        )

    async def _send_telegram_report_with_retry(self, user_id: int, file_path: str, filename: str):
        """
        Отправляет документ в Telegram с несколькими попытками в случае сетевых ошибок.
        """
        for i in range(config.TELEGRAM_SEND_ATTEMPTS):
            try:
                with open(file_path, "rb") as f:
                    await self.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        filename=filename,
                        read_timeout=config.TELEGRAM_SEND_TIMEOUT,
                        write_timeout=config.TELEGRAM_SEND_TIMEOUT,
                    )
                logger.info(f"✅ Файл {filename} успешно отправлен пользователю {user_id} (Telegram)")
                return
            except (TimedOut, NetworkError) as send_err:
                logger.warning(
                    f"Таймаут/сетевая ошибка при отправке пользователю {user_id} "
                    f"(попытка {i + 1}/{config.TELEGRAM_SEND_ATTEMPTS}): {send_err}"
                )
                if i < config.TELEGRAM_SEND_ATTEMPTS - 1:
                    # Экспоненциальная задержка: 2, 4, 8... секунд
                    await asyncio.sleep(config.TELEGRAM_RETRY_DELAY_SEC * (2 ** i))
                else:
                    logger.error(f"❌ Не удалось отправить файл пользователю {user_id} после всех попыток.", exc_info=True)
            except Exception as e:
                logger.error(f"❌ Критическая ошибка отправки файла пользователю {user_id}: {e}", exc_info=True)
                break # Нет смысла повторять при других ошибках

    async def _send_email_report_if_enabled(self, user_id: int, file_path: str):
        """
        Проверяет, включена ли у пользователя email-рассылка, и если да - отправляет отчет.
        """
        user = await get_user_for_email(user_id)
        # ИСПРАВЛЕНИЕ: Явно проверяем, что поле email не является None
        if user and user.email is not None:
            try:
                await send_email(to=user.email, attachments=[file_path])
                logger.info(f"📧 Email с файлом успешно отправлен на {user.email}")
            except Exception as email_err:
                logger.error(f"❌ Ошибка отправки email на {user.email}: {email_err}", exc_info=True)
        else:
            logger.info(f"У пользователя {user_id} email-рассылка неактивна или email не указан.")