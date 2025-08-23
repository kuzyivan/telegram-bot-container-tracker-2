import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_CHAT_ID
from datetime import datetime, timedelta, time
from sqlalchemy import text
from sqlalchemy.future import select
from db import SessionLocal
from models import TrackingSubscription, Tracking, User
from logger import get_logger

from utils.send_tracking import create_excel_file, create_excel_multisheet, get_vladivostok_filename
from utils.email_sender import send_email

import asyncio
from telegram.error import TimedOut, NetworkError

logger = get_logger(__name__)


async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[tracking] Запрос выгрузки всех подписок от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        logger.warning(f"[tracking] Отказ в доступе пользователю {user_id}")
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(text("SELECT * FROM tracking_subscriptions"))
            subs = result.fetchall()
            if not subs:
                await update.message.reply_text("Нет активных слежений.")
                return

            columns = result.keys()
            data = [dict(zip(columns, row)) for row in subs]
            df = pd.DataFrame(data)
            file_path = create_excel_file(df.values.tolist(), list(df.columns))
            filename = get_vladivostok_filename().replace("Дислокация", "tracking_subs")
            attempts = 3
            for i in range(attempts):
                try:
                    with open(file_path, "rb") as f:
                        await update.message.reply_document(
                            document=f,
                            filename=filename,
                            read_timeout=90.0,
                            write_timeout=90.0,
                        )
                    logger.info(f"[tracking] Выгрузка подписок успешно отправлена администратору.")
                    break
                except (TimedOut, NetworkError) as e:
                    logger.warning(f"[tracking] Таймаут при отправке документа админу (попытка {i+1}/{attempts}): {e}")
                    if i == attempts - 1:
                        raise
                    await asyncio.sleep(2 ** i)
    except Exception as e:
        logger.error(f"[tracking] Ошибка выгрузки подписок: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при экспорте подписок.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[stats] Запрос статистики за сутки от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        logger.warning(f"[stats] Отказ в доступе пользователю {user_id}")
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            query = text("""
                SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
                    STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
                FROM stats
                WHERE timestamp >= NOW() - INTERVAL '1 day'
                    AND user_id != :admin_id
                GROUP BY user_id, username
                ORDER BY запросов DESC
            """)
            result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
            rows = result.fetchall()

        if not rows:
            await update.message.reply_text("Нет статистики за последние сутки.")
            return

        text_msg = "📊 Статистика за последние 24 часа:\n\n"
        messages = []
        for row in rows:
            entry = (
                f"👤 {row.username} (ID: {row.user_id})\n"
                f"Запросов: {row.запросов}\n"
                f"Контейнеры: {row.контейнеры}\n\n"
            )
            if len(text_msg) + len(entry) > 4000:
                messages.append(text_msg)
                text_msg = ""
            text_msg += entry
        messages.append(text_msg)
        for msg in messages:
            await update.message.reply_text(msg)
        logger.info("[stats] Статистика успешно отправлена администратору.")
    except Exception as e:
        logger.error(f"[stats] Ошибка при формировании статистики: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при получении статистики.")


async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[exportstats] Запрос Excel-выгрузки всех запросов от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        logger.warning(f"[exportstats] Отказ в доступе пользователю {user_id}")
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            query = text("SELECT * FROM stats WHERE user_id != :admin_id")
            result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
            rows = result.fetchall()

        if not rows:
            await update.message.reply_text("Нет данных для экспорта.")
            return

        columns = list(result.keys())
        df = pd.DataFrame(rows, columns=columns)
        file_path = create_excel_file(df.values.tolist(), list(df.columns))
        filename = get_vladivostok_filename().replace("Дислокация", "Статистика")
        attempts = 3
        for i in range(attempts):
            try:
                with open(file_path, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=filename,
                        read_timeout=90.0,
                        write_timeout=90.0,
                    )
                logger.info(f"[exportstats] Статистика в Excel успешно отправлена администратору.")
                break
            except (TimedOut, NetworkError) as e:
                logger.warning(f"[exportstats] Таймаут при отправке документа админу (попытка {i+1}/{attempts}): {e}")
                if i == attempts - 1:
                    raise
                await asyncio.sleep(2 ** i)
    except Exception as e:
        logger.error(f"[exportstats] Ошибка выгрузки статистики: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при экспорте статистики.")


async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[test_notify] Запрос тестовой мульти-рассылки от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        logger.warning(f"[test_notify] Отказ в доступе пользователю {user_id}")
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(select(TrackingSubscription))
            subscriptions = result.scalars().all()

            columns = [
                'Номер контейнера', 'Станция отправления', 'Станция назначения',
                'Станция операции', 'Операция', 'Дата и время операции',
                'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
                'Номер вагона', 'Дорога операции'
            ]
            data_per_user = {}

            for sub in subscriptions:
                user_label = f"{sub.username or sub.user_id} (id:{sub.user_id})"
                rows = []
                for container in sub.containers:
                    res = await session.execute(
                        select(Tracking).filter(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
                    )
                    track = res.scalars().first()
                    if track:
                        rows.append([
                            track.container_number,
                            track.from_station,
                            track.to_station,
                            track.current_station,
                            track.operation,
                            track.operation_date,
                            track.waybill,
                            track.km_left,
                            track.forecast_days,
                            track.wagon_number,
                            track.operation_road
                        ])
                data_per_user[user_label] = rows if rows else [["Нет данных"] + [""] * (len(columns)-1)]

            file_path = create_excel_multisheet(data_per_user, columns)
            filename = get_vladivostok_filename("Тестовая дислокация")

            attempts = 3
            for i in range(attempts):
                try:
                    with open(file_path, "rb") as f:
                        await update.message.reply_document(
                            document=f,
                            filename=filename,
                            caption="Тестовая дислокация по всем подписчикам (разделено по листам)",
                            read_timeout=90.0,
                            write_timeout=90.0,
                        )
                    break
                except (TimedOut, NetworkError) as e:
                    logger.warning(f"[test_notify] Таймаут при отправке тестового файла (попытка {i+1}/{attempts}): {e}")
                    if i == attempts - 1:
                        raise
                    await asyncio.sleep(2 ** i)

            await update.message.reply_text(
                "✅ Тестовая мульти-рассылка готова и отправлена одним файлом.",
                read_timeout=30.0,
                write_timeout=30.0,
            )
            logger.info("[test_notify] Тестовая мульти-рассылка успешно отправлена.")

            # --- Email рассылка тестового файла администратору ---
            user_result = await session.execute(
                select(User).where(User.telegram_id == user_id, User.email_enabled == True)
            )
            admin_user = user_result.scalar_one_or_none()

            if admin_user and admin_user.email:
                try:
                    await send_email(
                        to=admin_user.email,
                        subject="Тестовая рассылка — Excel-файл с дислокацией",
                        body="Здравствуйте! Это тестовая email-рассылка от Telegram-бота. Во вложении — файл с мультилистом по подписчикам.",
                        attachments=[file_path]
                    )
                    logger.info(f"📧 Тестовое письмо отправлено на {admin_user.email}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке тестового email: {e}", exc_info=True)
            else:
                logger.warning(f"📭 Email не активирован для администратора или не указан.")

    except Exception as e:
        logger.error(f"[test_notify] Ошибка тестовой мульти-рассылки: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Ошибка при тестовой рассылке.",
            read_timeout=30.0,
            write_timeout=30.0,
        )