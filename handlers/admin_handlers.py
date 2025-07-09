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

logger = get_logger(__name__)

# /tracking — выгрузка всех подписок на слежение в Excel
async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[tracking] Запрос от {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
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
            logger.info("[tracking] Файл отправлен.")
    except Exception as e:
        logger.error(f"[tracking] Ошибка: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка экспорта.")


# /stats — статистика за сутки
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[stats] Запрос от {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            query = text("""
                SELECT user_id, COALESCE(username, '—') AS username, COUNT(*) AS запросов,
                       STRING_AGG(DISTINCT container_number, ', ') AS контейнеры
                FROM stats
                WHERE timestamp >= NOW() - INTERVAL '1 day' AND user_id != :admin_id
                GROUP BY user_id, username ORDER BY запросов DESC
            """)
            result = await session.execute(query, {'admin_id': ADMIN_CHAT_ID})
            rows = result.fetchall()

        if not rows:
            await update.message.reply_text("Нет статистики за последние сутки.")
            return

        msg = "\ud83d\udcca Статистика за 24 часа:\n\n"
        for row in rows:
            entry = f"\ud83d\udc64 {row.username} (ID: {row.user_id})\nЗапросов: {row.запросов}\nКонтейнеры: {row.контейнеры}\n\n"
            if len(msg) + len(entry) > 4000:
                await update.message.reply_text(msg)
                msg = ""
            msg += entry
        if msg:
            await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"[stats] Ошибка: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка получения статистики.")


# /exportstats — Excel-выгрузка всех запросов
async def exportstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[exportstats] Запрос от {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(text("SELECT * FROM stats WHERE user_id != :admin_id"), {'admin_id': ADMIN_CHAT_ID})
            rows = result.fetchall()
            if not rows:
                await update.message.reply_text("Нет данных.")
                return

            df = pd.DataFrame(rows, columns=result.keys())
            file_path = create_excel_file(df.values.tolist(), list(df.columns))
            filename = get_vladivostok_filename().replace("Дислокация", "Статистика")
            with open(file_path, "rb") as f:
                await update.message.reply_document(document=f, filename=filename)
    except Exception as e:
        logger.error(f"[exportstats] Ошибка: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка экспорта.")


# /testnotify — email + Excel в Telegram
async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"[test_notify] Запрос от {user_id}")
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("\u26d4\ufe0f Доступ запрещён.")
        return

    try:
        async with SessionLocal() as session:
            result = await session.execute(select(TrackingSubscription))
            subs = result.scalars().all()
            columns = [
                'Номер контейнера', 'Станция отправления', 'Станция назначения',
                'Станция операции', 'Операция', 'Дата и время операции',
                'Номер накладной', 'Расстояние оставшееся', 'Прогноз прибытия (дней)',
                'Номер вагона', 'Дорога операции'
            ]
            data_per_user = {}

            for sub in subs:
                rows = []
                for container in sub.containers:
                    res = await session.execute(
                        select(Tracking).filter(Tracking.container_number == container).order_by(Tracking.operation_date.desc())
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
                data_per_user[f"{sub.username or sub.user_id} (id:{sub.user_id})"] = rows

                user_result = await session.execute(select(User).where(User.id == sub.user_id))
                user_obj = user_result.scalar_one_or_none()

                if user_obj and user_obj.email:
                    logger.info(f"[test_notify] Отправка email: {user_obj.email}")
                    try:
                        success = await send_to_email(
                            user_obj.email,
                            "📦 Обновление контейнеров",
                            "Во вложении — свежий Excel с дислокацией контейнеров.",
                            generate_excel_report(rows, columns)
                        )
                        if success:
                            logger.info(f"[test_notify] ✅ Отправлено успешно на {user_obj.email}")
                        else:
                            logger.warning(f"[test_notify] ❌ Не удалось отправить на {user_obj.email}")
                    except Exception as e:
                        logger.error(f"[test_notify] ❌ Ошибка при отправке email {user_obj.email}: {e}", exc_info=True)

            file_path = create_excel_multisheet(data_per_user, columns)
            filename = get_vladivostok_filename("Тестовая дислокация")
            with open(file_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption="Тестовая дислокация по всем подписчикам (разделено по листам)"
                )
            await update.message.reply_text("\u2705 E-mail рассылка завершена. Excel отправлен.")

    except Exception as e:
        logger.error(f"[test_notify] Общая ошибка: {e}", exc_info=True)
        await update.message.reply_text("\u274c Ошибка при выполнении рассылки.")