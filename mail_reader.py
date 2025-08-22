# mail_reader.py
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from imap_tools import AND, MailBox
from sqlalchemy import text

from db import SessionLocal
from logger import get_logger
from models import Tracking

# импорт логики импорта терминальной базы
from services.container_importer import import_loaded_and_dispatch_from_excel

logger = get_logger(__name__)

# ───────────────────────────────────────────────────────────────────────────────
# Настройки почты и каталогов
# ───────────────────────────────────────────────────────────────────────────────
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.yandex.ru")

# Файлы дислокации (ежедневные/почасовые отчёты RZD) — старый парсер
DOWNLOAD_FOLDER = "downloads"
# Ежедневный отчёт терминала «Executive summary»
TERMINAL_FOLDER = "/root/AtermTrackBot/download_container"

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(TERMINAL_FOLDER, exist_ok=True)


# ───────────────────────────────────────────────────────────────────────────────
# Утилиты для Executive summary (терминальная база)
# ───────────────────────────────────────────────────────────────────────────────
def _today_vvo_str() -> str:
    """Дата во Владивостоке в формате DD.MM.YYYY для темы письма."""
    return datetime.now(ZoneInfo("Asia/Vladivostok")).strftime("%d.%m.%Y")


def _download_today_terminal_attachment() -> str | None:
    """
    Ищет в INBOX сегодняшнее письмо от aterminal@effex.ru с темой
    'Executive summary DD.MM.YYYY', сохраняет .xlsx в TERMINAL_FOLDER.
    Если точного совпадения нет, берёт самое свежее письмо от этого отправителя,
    у которого тема начинается с 'Executive summary'.
    Возвращает путь к сохранённому файлу или None.
    """
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL/PASSWORD не заданы — не могу загрузить Executive summary.")
        return None

    subject_today = f"Executive summary {_today_vvo_str()}"
    logger.info(f"📬 Ищу письмо: from=aterminal@effex.ru, subject='{subject_today}'")

    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder="INBOX") as m:
        # 1) сначала точное совпадение темы
        msgs = list(
            m.fetch(AND(from_="aterminal@effex.ru", subject=subject_today), reverse=True)
        )

        # 2) если нет — самое свежее, где тема начинается с "Executive summary"
        if not msgs:
            candidates = list(m.fetch(AND(from_="aterminal@effex.ru"), reverse=True))
            msgs = [
                x
                for x in candidates
                if (x.subject or "").strip().lower().startswith("executive summary")
            ]

        if not msgs:
            logger.info("📭 Письмо Executive summary не найдено.")
            return None

        msg = msgs[0]
        logger.info(f"✉️ Найдено письмо: '{msg.subject}' от {msg.date}")

        for att in msg.attachments or []:
            if att.filename and att.filename.lower().endswith(".xlsx"):
                save_path = os.path.join(TERMINAL_FOLDER, att.filename)
                with open(save_path, "wb") as f:
                    f.write(att.payload)
                logger.info(f"📥 Executive summary сохранён: {save_path}")
                return save_path

        logger.warning("⚠️ Во вложении письма нет .xlsx.")
        return None


async def fetch_terminal_excel_and_process():
    """
    Асинхронно скачивает сегодняшнее Executive summary и импортирует
    листы Loaded*/Dispatch* в таблицу terminal_containers.
    """
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, _download_today_terminal_attachment)
        if not filepath:
            logger.info("⚠ Нет файла Executive summary для импорта.")
            return

        logger.info(f"▶️ Импорт терминальной базы из: {filepath}")
        await import_loaded_and_dispatch_from_excel(filepath)
        logger.info("✅ Импорт терминальной базы завершён.")
    except Exception as e:
        logger.exception(f"❌ Ошибка импорта Executive summary: {e}")


# ───────────────────────────────────────────────────────────────────────────────
# Старая логика: дислокация контейнеров (tracking)
# ───────────────────────────────────────────────────────────────────────────────
def fetch_latest_excel() -> str | None:
    """
    Находит самое свежее .xlsx во входящих (без жёсткой фильтрации),
    сохраняет в DOWNLOAD_FOLDER, возвращает путь к файлу.
    Используется для обновления таблицы tracking.
    """
    latest_file: tuple | None = None
    latest_date: datetime | None = None

    if EMAIL is None or PASSWORD is None:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return None

    with MailBox(IMAP_SERVER).login(EMAIL, PASSWORD, initial_folder="INBOX") as mailbox:
        for msg in mailbox.fetch(reverse=True):
            for att in msg.attachments or []:
                if att.filename and att.filename.lower().endswith(".xlsx"):
                    if latest_date is None or msg.date > latest_date:
                        latest_date = msg.date
                        latest_file = (att, att.filename)

        if latest_file:
            filepath = os.path.join(DOWNLOAD_FOLDER, latest_file[1])
            with open(filepath, "wb") as f:
                f.write(latest_file[0].payload)
            return filepath

    return None


async def process_file(filepath: str):
    """
    Обновляет таблицу tracking из Excel (старый отчёт дислокации).
    Ожидает колонку 'Номер контейнера' и связанные поля.
    """
    import traceback

    try:
        df = pd.read_excel(filepath, skiprows=3)

        # Нормализуем имена столбцов (уберём лишние пробелы)
        df.columns = [str(c).strip() for c in df.columns]

        if "Номер контейнера" not in df.columns:
            raise ValueError("['Номер контейнера']")

        records = []
        for _, row in df.iterrows():
            # безопасно приводим километры
            km_raw = row.get("Расстояние оставшееся", 0)
            try:
                km_left = int(float(km_raw)) if pd.notna(km_raw) and km_raw != "" else 0
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

        async with SessionLocal() as session:
            # временная таблица для безопасного обновления
            await session.execute(
                text("CREATE TEMP TABLE IF NOT EXISTS tracking_tmp (LIKE tracking INCLUDING ALL)")
            )
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

        last_date = df["Дата и время операции"].dropna().max() if "Дата и время операции" in df.columns else None
        logger.info(f"✅ База tracking обновлена из файла {os.path.basename(filepath)}")
        logger.info(f"📦 Загружено строк: {len(records)}")
        if last_date is not None:
            logger.info(f"🕓 Последняя дата операции в файле: {last_date}")
        if "Станция операции" in df.columns:
            logger.info(f"🚉 Уникальных станций операции: {df['Станция операции'].nunique()}")
        logger.info(f"🚛 Уникальных контейнеров: {df['Номер контейнера'].nunique()}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {filepath}: {e}")
        logger.error(traceback.format_exc())


# ───────────────────────────────────────────────────────────────────────────────
# Публичные функции, вызываемые планировщиком/ботом
# ───────────────────────────────────────────────────────────────────────────────
async def check_mail():
    """
    Плановая проверка почты:
      1) пытаемся скачать и импортировать Executive summary (terminal_containers);
      2) обновляем дислокацию (tracking) из самого свежего .xlsx,
         если это не Executive summary.
    """
    logger.info("📬 [Scheduler] Запущена проверка почты по расписанию (каждые 20 минут)...")
    if not EMAIL or not PASSWORD:
        logger.error("❌ EMAIL или PASSWORD не заданы в переменных окружения.")
        return

    try:
        import asyncio

        loop = asyncio.get_running_loop()

        # Шаг 1. Executive summary → terminal_containers
        try:
            terminal_path = await loop.run_in_executor(None, _download_today_terminal_attachment)
            if terminal_path:
                logger.info("📦 Обнаружен файл терминальной базы. Запускаю импорт в terminal_containers...")
                await import_loaded_and_dispatch_from_excel(terminal_path)
                logger.info("✅ Импорт терминальной базы завершён успешно.")
        except Exception as e:
            logger.error(f"❌ Ошибка импорта Executive summary: {e}", exc_info=True)

        # Шаг 2. Дислокация → tracking (самый свежий .xlsx)
        result = await loop.run_in_executor(None, fetch_latest_excel)
        if result:
            filepath = result
            fname = os.path.basename(filepath).lower()
            # не кормим старому парсеру терминальные отчёты
            if fname.startswith("a-terminal ") or "executive" in fname:
                logger.info(f"ℹ️ Свежий .xlsx — Executive summary ({fname}). Для tracking не используем.")
            else:
                logger.info(f"📥 Скачан файл дислокации: {filepath}")
                await process_file(filepath)
        else:
            logger.info("⚠ Нет подходящих Excel-вложений для обновления tracking.")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке почты: {e}")


async def start_mail_checking():
    logger.info("📩 Запущена проверка почты (ручной запуск)...")
    await check_mail()
    logger.info("🔄 Проверка почты завершена.")