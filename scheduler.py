import logging
import asyncio
from datetime import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from telegram import Bot

from db import SessionLocal
from models import TrackingSubscription, Tracking
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from mail_reader import check_mail

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Asia/Vladivostok") # Установка часового пояса

def start_scheduler(bot: Bot):
    """Инициализирует и запускает задачи по расписанию."""
    # Задачи на отправку уведомлений
    scheduler.add_job(send_notifications, 'cron', hour=9, minute=0, args=[bot, time(9, 0)])
    scheduler.add_job(send_notifications, 'cron', hour=16, minute=0, args=[bot, time(16, 0)])
    # Задача на проверку почты
    scheduler.add_job(check_mail, 'interval', minutes=15)
    
    logger.info("🕓 Планировщик запущен, задачи добавлены.")
    scheduler.start()

async def send_notifications(bot: Bot, target_time: time):
    """
    Формирует и рассылает отчеты по отслеживаемым контейнерам.
    ИСПРАВЛЕНА ПРОБЛЕМА N+1 ЗАПРОСОВ.
    """
    logger.info(f"🚀 Запуск рассылки для времени {target_time.strftime('%H:%M')}...")
    
    async with SessionLocal() as session:
        # 1. Получаем все подписки для данного времени
        result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = result.scalars().all()

        if not subscriptions:
            logger.info(f"Для времени {target_time.strftime('%H:%M')} нет активных подписок.")
            return

        # 2. Собираем ВСЕ уникальные номера контейнеров из всех подписок
        all_container_numbers = {container for sub in subscriptions for container in sub.containers}

        if not all_container_numbers:
            logger.warning("Найдены подписки, но без указанных контейнеров.")
            return

        # 3. Делаем ОДИН запрос к БД, чтобы получить данные по всем контейнерам
        tracking_result = await session.execute(
            select(Tracking).where(Tracking.container_number.in_(all_container_numbers))
        )
        # 4. Преобразуем результат в словарь для быстрого доступа: {'НОМЕР': <Объект Tracking>}
        tracking_data_map = {track.container_number: track for track in tracking_result.scalars().all()}
        
        logger.info(f"Найдено {len(subscriptions)} подписок. Собрано {len(all_container_numbers)} уникальных контейнеров. "
                    f"Получено {len(tracking_data_map)} записей из БД.")

        # Колонки для Excel-файла
        columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ]
        
        # 5. Проходим по каждой подписке и формируем отчет, используя уже полученные данные
        for sub in subscriptions:
            rows = []
            not_found_containers = []
            for container_number in sub.containers:
                track_info = tracking_data_map.get(container_number)
                if track_info:
                    rows.append([
                        track_info.container_number,
                        track_info.from_station,
                        track_info.to_station,
                        track_info.current_station,
                        track_info.operation,
                        track_info.operation_date.strftime('%Y-%m-%d %H:%M:%S') if track_info.operation_date else '',
                        track_info.waybill,
                        track_info.km_left,
                        track_info.forecast_days,
                        track_info.wagon_number,
                        track_info.operation_road
                    ])
                else:
                    not_found_containers.append(container_number)

            if not rows:
                await bot.send_message(sub.user_id, f"📭 По вашим контейнерам ({', '.join(sub.containers)}) нет актуальных данных.")
                continue
            
            try:
                # ВЫНОСИМ БЛОКИРУЮЩУЮ ОПЕРАЦИЮ В EXECUTOR
                loop = asyncio.get_running_loop()
                file_path = await loop.run_in_executor(None, create_excel_file, rows, columns)
                
                filename = get_vladivostok_filename()
                
                with open(file_path, "rb") as f:
                    caption = f"✅ Дислокация по вашим контейнерам на {target_time.strftime('%H:%M')}."
                    if not_found_containers:
                        caption += f"\n\n⚠️ Не найдены данные для: {', '.join(not_found_containers)}"
                    
                    await bot.send_document(
                        chat_id=sub.user_id,
                        document=f,
                        filename=filename,
                        caption=caption
                    )
                logger.info(f"Отправлен отчет пользователю {sub.user_id} ({sub.username}) с {len(rows)} контейнерами.")
            except Exception as e:
                logger.error(f"Не удалось отправить отчет пользователю {sub.user_id}: {e}")

