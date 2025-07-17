import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from sqlalchemy.future import select
from sqlalchemy import text
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from logger import get_logger
from utils.send_tracking import (
    create_excel_file,
    create_excel_multisheet,
    get_vladivostok_filename,
    generate_excel_report,
)
from utils.email_sender import send_to_email
from typing import Optional

logger = get_logger(__name__)

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выгрузка всех подписок на слежение в Excel"""
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[tracking] Запрос от {user_id}")
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(text("SELECT * FROM tracking_subscriptions"))
            subs = result.fetchall()
            
            if not subs:
                await update.message.reply_text("Нет активных слежений.")
                return

            df = pd.DataFrame([dict(zip(result.keys(), row)) for row in subs])
            file_path = create_excel_file(df.values.tolist(), list(df.columns))
            filename = get_vladivostok_filename().replace("Дислокация", "tracking_subs")
            
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
            
            logger.info("[tracking] Файл отправлен администратору.")
            
    except Exception as e:
        logger.error(f"[tracking] Ошибка экспорта подписок: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при экспорте подписок.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика запросов за сутки"""
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[stats] Запрос статистики от {user_id}")
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            query = text("""
                SELECT 
                    user_id, 
                    COALESCE(username, '—') AS username, 
                    COUNT(*) AS запросов,
                    STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
                FROM stats
                WHERE timestamp >= NOW() - INTERVAL '1 day' AND user_id != :admin_id
                GROUP BY user_id, username 
                ORDER BY запросов DESC
            """)
            result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
            rows = result.fetchall()

            if not rows:
                await update.message.reply_text("📊 Нет статистики за последние сутки.")
                return

            msg = "📊 Статистика за 24 часа:\n\n"
            for row in rows:
                entry = (
                    f"👤 {row.username} (ID: {row.user_id})\n"
                    f"🔢 Запросов: {row.запросов}\n"
                    f"📦 Контейнеры: {row.контейнеры}\n\n"
                )
                
                if len(msg) + len(entry) > 4000:
                    await update.message.reply_text(msg)
                    msg = ""
                msg += entry
            
            if msg:
                await update.message.reply_text(msg)
                
            logger.info(f"[stats] Отправлено {len(rows)} записей статистики")
            
    except Exception as e:
        logger.error(f"[stats] Ошибка получения статистики: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при получении статистики.")

async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт всей статистики в Excel"""
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[exportstats] Запрос от {user_id}")
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM stats WHERE user_id != :admin_id"), 
                {'admin_id': ADMIN_CHAT_ID}
            )
            rows = result.fetchall()
            
            if not rows:
                await update.message.reply_text("Нет данных для экспорта.")
                return

            df = pd.DataFrame(rows, columns=result.keys())
            file_path = create_excel_file(df.values.tolist(), list(df.columns))
            filename = get_vladivostok_filename().replace("Дислокация", "Статистика")
            
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
                
            logger.info(f"[exportstats] Экспортировано {len(rows)} записей")
            
    except Exception as e:
        logger.error(f"[exportstats] Ошибка экспорта: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при экспорте статистики.")

async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая рассылка уведомлений"""
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[test_notify] Запуск тестовой рассылки по запросу {user_id}")
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            # Получаем все активные подписки
            result = await session.execute(select(TrackingSubscription))
            subscriptions = result.scalars().all()
            
            if not subscriptions:
                await update.message.reply_text("ℹ️ Нет активных подписок для тестирования.")
                return

            columns = [
                'Номер контейнера', 'Станция отправления', 'Станция назначения',
                'Станция операции', 'Операция', 'Дата и время операции',
                'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
                'Номер вагона', 'Дорога операции'
            ]
            
            data_per_user = {}
            email_count = 0
            telegram_count = 0
            skipped_count = 0

            for sub in subscriptions:
                logger.info(
                    f"[test_notify] Обработка подписки ID {sub.id} "
                    f"(user_id={sub.user_id}, канал={sub.delivery_channel})"
                )

                # Получаем данные по контейнерам
                rows = []
                for container in sub.containers:
                    res = await session.execute(
                        select(Tracking)
                        .filter(Tracking.container_number == container)
                        .order_by(Tracking.operation_date.desc())
                    )
                    track = res.scalars().first()
                    if track:
                        rows.append([
                            track.container_number, track.from_station, track.to_station,
                            track.current_station, track.operation, track.operation_date,
                            track.waybill, track.km_left, track.forecast_days,
                            track.wagon_number, track.operation_road
                        ])
                
                if not rows:
                    rows = [["Нет данных"] + [""] * 10]
                
                user_label = f"{sub.username or 'Без имени'} (ID:{sub.user_id})"
                data_per_user[user_label] = rows

                # Получаем данные пользователя
                user = await session.get(User, sub.user_id)
                if not user:
                    logger.warning(f"[test_notify] Пользователь {sub.user_id} не найден")
                    skipped_count += 1
                    continue

                # Логирование перед отправкой
                logger.info(
                    f"[test_notify] Подготовка уведомления для {user.email}. "
                    f"Канал: {sub.delivery_channel}, "
                    f"Контейнеров: {len(sub.containers)}, "
                    f"Данных: {len(rows)} строк"
                )

                # Отправка в Telegram
                if sub.delivery_channel in ["telegram", "both"]:
                    try:
                        file_path = create_excel_file(rows, columns)
                        filename = get_vladivostok_filename()
                        
                        with open(file_path, "rb") as f:
                            await context.bot.send_document(
                                chat_id=sub.user_id,
                                document=f,
                                filename=filename,
                                caption="Тестовое уведомление о контейнерах"
                            )
                        telegram_count += 1
                        logger.info(f"[test_notify] Telegram отправлен пользователю {sub.user_id}")
                    except Exception as e:
                        logger.error(
                            f"[test_notify] Ошибка отправки в Telegram пользователю {sub.user_id}: {str(e)}",
                            exc_info=True
                        )

                # Отправка на email
                if sub.delivery_channel in ["email", "both"] and user.email:
                    try:
                        excel_bytes = generate_excel_report(rows, columns)
                        
                        logger.info(
                            f"[test_notify] Отправка email на {user.email}. "
                            f"Размер вложения: {len(excel_bytes) if excel_bytes else 0} байт"
                        )
                        
                        success = await send_to_email(
                            to_email=user.email,
                            subject="Тестовое уведомление о контейнерах",
                            text="Это тестовое сообщение от бота отслеживания контейнеров.",
                            attachment_bytes=excel_bytes,
                            attachment_filename=get_vladivostok_filename()
                        )
                        
                        if success:
                            email_count += 1
                            logger.info(f"[test_notify] Email отправлен на {user.email}")
                        else:
                            logger.warning(f"[test_notify] Не удалось отправить email на {user.email}")
                    except Exception as e:
                        logger.error(
                            f"[test_notify] Ошибка отправки email на {user.email}: {str(e)}",
                            exc_info=True
                        )
                else:
                    skipped_count += 1
                    logger.info(
                        f"[test_notify] Пропуск email для {sub.user_id}: "
                        f"канал={sub.delivery_channel}, email={bool(user.email)}"
                    )

            # Отправка сводного отчета администратору
            file_path = create_excel_multisheet(data_per_user, columns)
            filename = get_vladivostok_filename("Тестовая рассылка")
            
            with open(file_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=(
                        "📊 Итоги тестовой рассылки:\n"
                        f"📨 Email: {email_count}\n"
                        f"📱 Telegram: {telegram_count}\n"
                        f"⏭ Пропущено: {skipped_count}"
                    )
                )
            
            logger.info(
                f"[test_notify] Рассылка завершена. "
                f"Email: {email_count}, Telegram: {telegram_count}, Пропущено: {skipped_count}"
            )

    except Exception as e:
        logger.critical(f"[test_notify] Критическая ошибка: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка при рассылке. Проверьте логи.")

# Регистрация обработчиков
def register_admin_handlers(application):
    application.add_handler(CommandHandler("tracking", tracking))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("exportstats", exportstats))
    application.add_handler(CommandHandler("testnotify", test_notify))
    
    logger.info("Админские команды зарегистрированы")