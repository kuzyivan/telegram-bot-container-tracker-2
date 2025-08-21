# mail_reader.py
from __future__ import annotations

import os
import asyncio
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text
from imap_tools import MailBox, AND  # оптимизированный доступ к IMAP

from db import SessionLocal
from models import Tracking  # старая логика дислокации остаётся
from logger import get_logger

# === Новое: импорт для терминальной базы ===
from services.container_importer import import_loaded_and_dispatch_from_excel

# Встроенная зона (Python 3.9+). Если недоступно, можно заменить на pytz.
try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # fallback на pytz при желании
    ZoneInfo = None  # noqa

logger = get_logger(__name__)

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.yandex.ru")

# Папки для разных задач
DOWNLOAD_FOLDER = "downloads"  # для старой логики дислокации
TERMINAL_FOLDER = "data"       # для Executive summary (терминальная база)

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(TERMINAL_FOLDER, exist_ok=True)


# =========================
# СТАРАЯ ЛОГИКА: ДИСЛОКАЦИЯ
# =========================
async def check_mail():
    """
    Периодическая проверка почты для загрузки дислокации (старый поток).
    Берёт самый свежий .xlsx из INBOX и обновляет таблицу tracking.
    """
    logger.info("📬 [Scheduler] Запущена проверка почты (каждые 20 минут)...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, fetch_latest_excel)
        if filepath:
            logger.info(f"📥 Скачан самый свежий файл (дислокация): {filepath}")
            await process_file(filepath)
        else:
            logger.info("⚠ Нет подходящих Excel-вложений в почте, обновление tracking не требуется.")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты (tracking): {e}", exc_info=True)


def fetch_latest_excel() -> Optional[str]:
    """
    Синхронная часть: найти и сохранить самый свежий .xlsx для старой логики.
    """
    latest_file = None
    latest_date = None
    if EMAIL is None or PASSWORD is None:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return None

    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder="INBOX") as mailbox:
        for msg in mailbox.fetch(reverse=True):
            for att in msg.attachments:
                if att.filename and att.filename.lower().endswith(".xlsx"):
                    msg_date = msg.date
                    if latest_date is None or (msg_date and msg_date > latest_date):
                        latest_date = msg_date
                        latest_file = (att, att.filename)
        if latest_file:
            filepath = os.path.join(DOWNLOAD_FOLDER, latest_file[1])
            with open(filepath, "wb") as f:
                f.write(latest_file[0].payload)
            return filepath
    return None


async def process_file(filepath: str):
    """
    Обновление таблицы tracking из Excel (старый поток). Через temp-таблицу.
    """
    import traceback
    try:
        df = pd.read_excel(filepath, skiprows=3)
        if "Номер контейнера" not in df.columns:
            raise ValueError("Ожидалась колонка 'Номер контейнера' в файле дислокации")

        records = []
        for _, row in df.iterrows():
            km_left_val = row.get("Расстояние оставшееся", 0)
            try:
                km_left = int(km_left_val or 0)
            except Exception:
                km_left = 0
            forecast_days = round(km_left / 600, 1) if km_left else 0.0

            record = Tracking(
                container_number=str(row["Номер контейнера"]).strip().upper(),
                from_station=str(row.get("Станция отправления", "")).strip(),
                to_station=str(row.get("Станция назначения", "")).strip(),
                current_station=str(row.get("Станция операции", "")).strip(),
                operation=str(row.get("Операция", "")).strip(),
                operation_date=str(row.get("Дата и время операции", "")).strip(),
                waybill=str(row.get("Номер накладной", "")).strip(),
                km_left=km_left,
                forecast_days=forecast_days,
                wagon_number=str(row.get("Номер вагона", "")).strip(),
                operation_road=str(row.get("Дорога операции", "")).strip(),
            )
            records.append(record)

        # Асинхронная работа с БД (через temp-таблицу)
        async with SessionLocal() as session:
            await session.execute(text("CREATE TEMP TABLE IF NOT EXISTS tracking_tmp (LIKE tracking INCLUDING ALL)"))
            await session.execute(text("TRUNCATE tracking_tmp"))

            for record in records:
                await session.execute(
                    text(
                        "INSERT INTO tracking_tmp "
                        "(container_number, from_station, to_station, current_station, operation, "
                        "operation_date, waybill, km_left, forecast_days, wagon_number, operation_road) "
                        "VALUES (:container_number, :from_station, :to_station, :current_station, :operation, "
                        ":operation_date, :waybill, :km_left, :forecast_days, :wagon_number, :operation_road)"
                    ),
                    {
                        "container_number": record.container_number,
                        "from_station": record.from_station,
                        "to_station": record.to_station,
                        "current_station": record.current_station,
                        "operation": record.operation,
                        "operation_date": record.operation_date,
                        "waybill": record.waybill,
                        "km_left": record.km_left,
                        "forecast_days": record.forecast_days,
                        "wagon_number": record.wagon_number,
                        "operation_road": record.operation_road,
                    },
                )

            await session.commit()
            await session.execute(text("TRUNCATE tracking"))
            await session.execute(text("INSERT INTO tracking SELECT * FROM tracking_tmp"))
            await session.execute(text("DROP TABLE IF EXISTS tracking_tmp"))
            await session.commit()

        last_date = df["Дата и время операции"].dropna().max()
        logger.info(f"✅ tracking обновлён из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records)}")
        logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")
        logger.error(traceback.format_exc())


async def start_mail_checking():
    logger.info("📩 Запущена проверка почты (ручной запуск старой логики)...")
    await check_mail()
    logger.info("🔄 Проверка почты завершена.")


# ========================================
# НОВАЯ ЛОГИКА: Executive summary (терминальная база)
# ========================================
def _today_vvo_str() -> str:
    """
    Дата во Владивостоке для темы письма (DD.MM.YYYY).
    Если ZoneInfo недоступен (редкий случай), используем локальную дату.
    """
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Vladivostok")).strftime("%d.%m.%Y")
    # fallback — локальная система (может отличаться от Владивостока)
    return datetime.now().strftime("%d.%m.%Y")


def _download_today_terminal_attachment() -> Optional[str]:
    """
    Оптимизированный поиск: находит сегодняшнее письмо от aterminal@effex.ru с темой
    'Executive summary DD.MM.YYYY', сохраняет .xlsx в TERMINAL_FOLDER.
    Возвращает полный путь к файлу или None.
    """
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL/PASSWORD не заданы — не могу загрузить Executive summary.")
        return None

    subject_today = f"Executive summary {_today_vvo_str()}"
    SENDER = "aterminal@effex.ru"
    PRIMARY_LIMIT = 5     # точный запрос (меньше писем)
    FALLBACK_LIMIT = 50   # запасной поиск по отправителю

    logger.info(f"📬 Поиск письма: '{subject_today}' от {SENDER}")

    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder="INBOX") as mailbox:
        # 1) Точное совпадение: отправитель + точная тема за сегодня
        exact_msgs = list(
            mailbox.fetch(
                AND(from_=SENDER, subject=subject_today),
                reverse=True,
                limit=PRIMARY_LIMIT,
            )
        )
        candidates = exact_msgs

        # 2) Fallback: свежие письма от отправителя с темой, начинающейся на "Executive summary"
        if not candidates:
            fallback_msgs = list(
                mailbox.fetch(
                    AND(from_=SENDER),
                    reverse=True,
                    limit=FALLBACK_LIMIT,
                )
            )
            candidates = [
                msg for msg in fallback_msgs
                if (msg.subject or "").lower().startswith("executive summary")
            ]

        if not candidates:
            logger.info("📭 Письмо Executive summary не найдено.")
            return None

        msg = candidates[0]
        logger.info(f"✉️ Найдено письмо: '{msg.subject}' от {msg.date}")

        # Ищем .xlsx во вложениях
        for att in (msg.attachments or []):
            if att.filename and att.filename.lower().endswith(".xlsx"):
                save_path = os.path.join(TERMINAL_FOLDER, att.filename)
                with open(save_path, "wb") as f:
                    f.write(att.payload)
                logger.info(f"📥 Вложение сохранено: {save_path}")
                return save_path

        logger.warning("⚠️ Во вложении письма нет .xlsx файлов.")
        return None


async def fetch_terminal_excel_and_process():
    """
    Асинхронная оболочка: скачивает сегодняшнее Executive summary и импортирует его
    в таблицу terminal_containers через services.container_importer.
    """
    try:
        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, _download_today_terminal_attachment)
        if not filepath:
            logger.info("⚠ Нет файла Executive summary для импорта.")
            return

        logger.info(f"▶️ Запускаю импорт терминальной базы из: {filepath}")
        await import_loaded_and_dispatch_from_excel(filepath)
        logger.info("✅ Импорт терминальной базы завершён.")
    except Exception as e:
        logger.exception(f"❌ Ошибка импорта Executive summary: {e}")