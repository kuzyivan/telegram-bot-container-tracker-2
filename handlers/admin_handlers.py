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

from utils.send_tracking import (
    create_excel_file,
    create_excel_multisheet,
    get_vladivostok_filename,
    generate_excel_report,
)
from utils.email_sender import send_to_email

logger = get_logger(__name__)

# /tracking — выгрузка всех подписок на слежение в Excel
async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[tracking] Запрос выгрузки всех подписок от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        logger.warning(f"[tracking] Отказ в доступе пользователю {user_id}")
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
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
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
            logger.info("[tracking] Выгрузка подписок успешно отправлена администратору.")
    except Exception as e:
        logger.error(f"[tracking] Ошибка выгрузки подписок: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка при экспорте подписок.")

# /stats — статистика запросов за последние сутки в текстовом виде
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[stats] Запрос статистики за сутки от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
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

        text_msg = "\ud83d\udcca Статистика за последние 24 часа:\n\n"
        messages = []
        for row in rows:
            entry = (
                f"\ud83d\udc64 {row.username} (ID: {row.user_id})\n"
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
        await update.message.reply_text("\u274c Ошибка при получении статистики.")

# /exportstats — Excel выгрузка всех запросов за всё время (кроме админа)
async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[exportstats] Запрос Excel-выгрузки всех запросов от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
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
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=filename)
        logger.info("[exportstats] Статистика в Excel успешно отправлена администратору.")
    except Exception as e:
        logger.error(f"[exportstats] Ошибка выгрузки статистики: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка при экспорте статистики.")

# /testnotify — один Excel, все подписки, каждый пользователь отдельным листом + рассылка каждому e-mail
async def test_notify(update, context):
    user = update.effective_user
    user_id = user.id if user is not None else None
    logger.info(f"[test_notify] Запрос тестовой мульти-рассылки от пользователя {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
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
                if not rows:
                    rows = [["Нет данных"] + [""] * (len(columns) - 1)]
                data_per_user[user_label] = rows

                user_result = await session.execute(
                    select(User).where(User.id == sub.user_id)
                )
                user_obj = user_result.scalar_one_or_none()

                if (
                    sub.delivery_channel in ("email", "both")
                    and user_obj
                    and user_obj.email
                    and user_obj.email_enabled
                ):
                    excel_bytes = generate_excel_report(rows, columns)
                    try:
                        await send_to_email(
                            user_obj.email,
                            "🪪 Тестовая e-mail рассылка по подписке",
                            "Вложение — твой Excel по всем контейнерам.",
                            excel_bytes
                        )
                        logger.info(f"[test_notify] Тестовое письмо отправлено на {user_obj.email}")
                    except Exception as mail_err:
                        logger.error(f"[test_notify] ❌ Ошибка при отправке email {user_obj.email}: {mail_err}", exc_info=True)
                else:
                    logger.info(
                        f"[test_notify] Пользователь {sub.user_id} — рассылка по email пропущена. "
                        f"Причина: delivery_channel={sub.delivery_channel}, email={getattr(user_obj, 'email', None)}, enabled={getattr(user_obj, 'email_enabled', None)}"
                    )

            file_path = create_excel_multisheet(data_per_user, columns)
            filename = get_vladivostok_filename("Тестовая дислокация")
            with open(file_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption="Тестовая дислокация по всем подписчикам (разделено по листам)"
                )
            await update.message.reply_text("\u2705 Тестовая мульти-рассылка готова и отправлена одним файлом.")
            logger.info("[test_notify] Тестовая мульти-рассылка успешно отправлена.")

    except Exception as e:
        logger.error(f"[test_notify] Ошибка тестовой мульти-рассылки: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка при тестовой рассылке.")