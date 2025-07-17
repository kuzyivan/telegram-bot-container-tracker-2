import pandas as pd
import io
import aiosmtplib
from email.message import EmailMessage
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
import tempfile
import re

from logger import get_logger
from config import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, FROM_EMAIL

logger = get_logger(__name__)

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB


def create_excel_file(rows, columns):
    """
    Создание Excel-файла (один лист).
    """
    logger.info("Создание Excel-файла (один лист) с %d строк(ами)", len(rows))
    try:
        df = pd.DataFrame(rows, columns=columns)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Экспорт')
                worksheet = writer.sheets['Экспорт']
                header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for cell in worksheet[1]:
                    cell.fill = header_fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
            logger.info("Excel-файл успешно создан: %s", tmp.name)
            return tmp.name
    except Exception as e:
        logger.error("Ошибка при создании Excel-файла: %s", e, exc_info=True)
        raise


def clean_sheet_name(name):
    """
    Очистка имени листа для Excel.
    """
    clean = re.sub(r'[:\\/?*\[\]]', '_', str(name))[:31]
    logger.debug("Очищено имя листа: %s -> %s", name, clean)
    return clean


def create_excel_multisheet(data_per_user, columns):
    """
    Мультилистовой Excel-файл (по пользователям).
    """
    logger.info("Создание мультилистового Excel-файла для %d пользователей", len(data_per_user))
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                for user_label, rows in data_per_user.items():
                    sheet_name = clean_sheet_name(user_label)
                    df = pd.DataFrame(rows, columns=columns)
                    df.to_excel(writer, index=False, sheet_name=sheet_name)
                    worksheet = writer.sheets[sheet_name]
                    header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                    for cell in worksheet[1]:
                        cell.fill = header_fill
                    for col in worksheet.columns:
                        max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                        worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
            logger.info("Мультилистовый Excel-файл успешно создан: %s", tmp.name)
            return tmp.name
    except Exception as e:
        logger.error("Ошибка при создании мультилистового Excel-файла: %s", e, exc_info=True)
        raise


def get_vladivostok_filename(prefix="Слежение контейнеров"):
    """
    Имя файла по Владивостокскому времени (UTC+10).
    """
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    filename = f"{prefix} {vladivostok_time.strftime('%H-%M')}.xlsx"
    logger.debug("Сгенерировано имя файла для Владивостока: %s", filename)
    return filename


def generate_excel_report(rows, columns):
    """
    Генерация Excel-файла в памяти (в виде байтов).
    """
    logger.info("Генерация Excel-файла в байтах")
    try:
        df = pd.DataFrame(rows, columns=columns)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Экспорт')
            worksheet = writer.sheets['Экспорт']
            header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
            for cell in worksheet[1]:
                cell.fill = header_fill
            for col in worksheet.columns:
                max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
        output.seek(0)
        logger.info("Excel-файл успешно сгенерирован в памяти")
        return output.read()
    except Exception as e:
        logger.error("Ошибка при генерации Excel-файла в байтах: %s", e, exc_info=True)
        raise


async def send_to_email(to_email, subject, text, file_bytes=None):
    """
    Отправка письма с вложением Excel-файла (по e-mail).
    """
    if not to_email or not isinstance(to_email, str):
        raise ValueError("Invalid email address")

    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)

    if file_bytes:
        if len(file_bytes) > MAX_ATTACHMENT_SIZE:
            raise ValueError("Attachment size exceeds limit")
        msg.add_attachment(
            file_bytes,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="tracking_report.xlsx"
        )

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            start_tls=SMTP_PORT != 465,
            timeout=10
        )
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Email failed to {to_email}: {str(e).replace(SMTP_PASS, '***')}")
        raise