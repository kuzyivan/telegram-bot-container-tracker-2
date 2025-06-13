from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from datetime import time
import logging

from db import SessionLocal
from models import TrackingSubscription, Tracking
from utils.send_tracking import create_excel_file, get_vladivostok_filename
from mail_reader import check_mail

# Устанавливаем правильную таймзону для планировщика
scheduler = AsyncIOScheduler(timezone="Asia/Vladivostok")
logger = logging.getLogger(__name__)

def start_scheduler(bot):
    """
    Добавляет все задачи в планировщик и запускает его.
    """
    # Рассылка уведомлений по времени Владивостока
    scheduler.add_job(send_notifications, 'cron', hour=9, minute=0, args=[bot, time(9, 0)], misfire_grace_time=3600)
    scheduler.add_job(send_notifications, 'cron', hour=16, minute=0, args=[bot, time(16, 0)], misfire_grace_time=3600)
    
    # Проверка почты каждые 15 минут
    scheduler.add_job(check_mail, 'interval', minutes=15, misfire_grace_time=60)

    logger.info("🕓 Планировщик запущен со всеми задачами.")
    scheduler.start()

async def send_notifications(bot, target_time: time):
    """
    Формирует и рассылает отчеты по отслеживаемым контейнерам.
    Оптимизировано для минимизации запросов к БД.
    """
    logger.info(f"🚀 Запуск рассылки для времени {target_time.strftime('%H:%M')}")
    async with SessionLocal() as session:
        # 1. Находим все подписки на указанное время
        sub_result = await session.execute(
            select(TrackingSubscription).where(TrackingSubscription.notify_time == target_time)
        )
        subscriptions = sub_result.scalars().all()

        if not subscriptions:
            logger.info(f"ℹ️ Нет подписок для времени {target_time.strftime('%H:%M')}.")
            return

        # 2. Собираем ВСЕ уникальные контейнеры из всех подписок
        all_containers_to_find = {cn for sub in subscriptions for cn in sub.containers}

        if not all_containers_to_find:
            return

        # 3. Делаем ОДИН запрос к БД для всех контейнеров
        tracking_result = await session.execute(
            select(Tracking).filter(Tracking.container_number.in_(all_containers_to_find))
        )
        tracking_data = {track.container_number: track for track in tracking_result.scalars().all()}
        logger.info(f"🔍 Найдено {len(tracking_data)} записей для {len(all_containers_to_find)} контейнеров.")

        columns = [
            'Номер контейнера', 'Станция отправления', 'Станция назначения',
            'Станция операции', 'Операция', 'Дата и время операции',
            'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
            'Номер вагона', 'Дорога операции'
        ]

        # 4. Формируем и отправляем отчет для каждого подписчика
        for sub in subscriptions:
            rows_for_user = []
            for container_num in sub.containers:
                track = tracking_data.get(container_num)
                if track:
                    rows_for_user.append([
                        track.container_number, track.from_station, track.to_station,
                        track.current_station, track.operation, track.operation_date,
                        track.waybill, track.km_left, track.forecast_days,
                        track.wagon_number, track.operation_road
                    ])
            
            if not rows_for_user:
                try:
                    await bot.send_message(sub.user_id, f"📭 По вашим контейнерам ({', '.join(sub.containers)}) нет актуальных данных.")
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление об отсутствии данных пользователю {sub.user_id}: {e}")
                continue

            try:
                file_path = create_excel_file(rows_for_user, columns)
                filename = get_vladivostok_filename()
                with open(file_path, "rb") as f:
                    await bot.send_document(
                        chat_id=sub.user_id,
                        document=f,
                        filename=filename,
                        caption=f"Дислокация по вашим контейнерам на {target_time.strftime('%H:%M')}"
                    )
                logger.info(f"✅ Отправлен отчет пользователю {sub.user_id} ({len(rows_for_user)} строк).")
            except Exception as e:
                logger.error(f"❌ Не удалось отправить отчет пользователю {sub.user_id}: {e}")
