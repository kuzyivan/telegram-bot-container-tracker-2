# services/notification_service.py
import asyncio
from datetime import time
from telegram import Bot
from telegram.error import TimedOut, NetworkError, Forbidden

import config
from logger import get_logger
from queries.notification_queries import (
    get_subscriptions_for_time,
    get_tracking_data_for_containers,
)
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from utils.email_sender import send_email
from services.railway_router import get_remaining_distance_on_route

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_scheduled_notifications(self, target_time: time):
        subscriptions = await get_subscriptions_for_time(target_time)
        logger.info(f"Найдено {len(subscriptions)} подписок для рассылки в {target_time.strftime('%H:%M')}.")
        tasks = [self._process_single_subscription(sub) for sub in subscriptions]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_single_subscription(self, subscription):
        """
        Обрабатывает одну подписку: получает данные, ПЕРЕСЧИТЫВАЕТ РАССТОЯНИЕ,
        создает отчет и отправляет его.
        """
        user_id = subscription.user_telegram_id
        containers = list(subscription.containers)
        sub_name = subscription.subscription_name
        logger.info(f"Обработка подписки '{sub_name}' для пользователя {user_id} на контейнеры: {containers}")

        report_data_from_db = await get_tracking_data_for_containers(containers)

        if not report_data_from_db:
            try:
                await self.bot.send_message(user_id, f"📝 По вашей подписке '{sub_name}' нет данных по отслеживаемым контейнерам.")
                logger.warning(f"Нет данных для подписки '{sub_name}' (пользователь {user_id}). Отправлено текстовое уведомление.")
            except Forbidden:
                logger.warning(f"Не удалось уведомить пользователя {user_id} об отсутствии данных (бот заблокирован).")
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id} об отсутствии данных: {e}")
            return

        # Создаем новый список данных с пересчитанными расстояниями
        final_report_data = []
        for row in report_data_from_db:
            # Преобразуем Row в изменяемый список
            row_list = list(row)
            
            # Вызываем сервис для пересчета расстояния
            remaining_distance = await get_remaining_distance_on_route(
                start_station=row.from_station,
                end_station=row.to_station,
                current_station=row.current_station
            )
            
            if remaining_distance is not None:
                # Обновляем расстояние (индекс 7 в запросе get_tracking_data_for_containers)
                row_list[7] = remaining_distance
                # Обновляем прогноз (индекс 8)
                forecast = round(remaining_distance / 600 + 1, 1) if remaining_distance > 0 else 0
                row_list[8] = forecast
            
            final_report_data.append(row_list)

        # Используем обновленные данные для создания файла
        file_path = await asyncio.to_thread(create_excel_file, final_report_data, config.TRACKING_REPORT_COLUMNS)
        filename = get_vladivostok_filename(prefix=sub_name)

        send_tasks = [self._send_telegram_report_with_retry(user_id, file_path, filename, sub_name)]
        if subscription.target_emails:
            for user_email in subscription.target_emails:
                send_tasks.append(self._send_email_report(user_email.email, file_path, sub_name))
        
        await asyncio.gather(*send_tasks)

    async def _send_telegram_report_with_retry(self, user_id: int, file_path: str, filename: str, sub_name: str):
        for i in range(config.TELEGRAM_SEND_ATTEMPTS):
            try:
                with open(file_path, "rb") as f:
                    await self.bot.send_document(
                        chat_id=user_id, document=f, filename=filename,
                        caption=f"Отчет по подписке '{sub_name}'",
                        read_timeout=config.TELEGRAM_SEND_TIMEOUT,
                        write_timeout=config.TELEGRAM_SEND_TIMEOUT,
                    )
                logger.info(f"✅ Файл {filename} успешно отправлен пользователю {user_id} (Telegram)")
                return
            except Forbidden:
                logger.warning(f"❌ Не удалось отправить файл пользователю {user_id} (бот заблокирован).")
                break
            except (TimedOut, NetworkError) as send_err:
                logger.warning(f"Таймаут/сетевая ошибка при отправке пользователю {user_id} (попытка {i + 1}/{config.TELEGRAM_SEND_ATTEMPTS}): {send_err}")
                if i < config.TELEGRAM_SEND_ATTEMPTS - 1:
                    await asyncio.sleep(config.TELEGRAM_RETRY_DELAY_SEC * (2 ** i))
                else:
                    logger.error(f"❌ Не удалось отправить файл пользователю {user_id} после всех попыток.", exc_info=True)
            except Exception as e:
                logger.error(f"❌ Критическая ошибка отправки файла пользователю {user_id}: {e}", exc_info=True)
                break

    async def _send_email_report(self, email_address: str, file_path: str, sub_name: str):
        try:
            subject = f"Отчет по подписке '{sub_name}'"
            await send_email(to=email_address, subject=subject, attachments=[file_path])
            logger.info(f"📧 Email с отчетом по подписке '{sub_name}' успешно отправлен на {email_address}")
        except Exception as email_err:
            logger.error(f"❌ Ошибка отправки email на {email_address}: {email_err}", exc_info=True)