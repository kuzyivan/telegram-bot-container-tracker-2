import os
import smtplib
from email.message import EmailMessage
from logger import get_logger

logger = get_logger(__name__)

# SMTP-настройки из .env
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


async def send_email(to, subject, body, attachments=None):
    """
    Отправляет письмо с вложениями.

    Args:
        to (str): email-адрес получателя
        subject (str): тема письма
        body (str): текст письма
        attachments (list[str]): пути к Excel-файлам
    """
    message = EmailMessage()
    message["From"] = SMTP_USER
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    attachments = attachments or []
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
            filename = os.path.basename(path)
            message.add_attachment(
                data,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename,
            )
        except Exception as e:
            logger.error(f"❌ Ошибка при добавлении вложения {path}: {e}", exc_info=True)

    # --- Основная отправка
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.set_debuglevel(1)  # Включаем отладку SMTP — всё выведется в stdout
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(message)
        logger.info(f"📧 Успешно отправлено письмо на {to}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке письма на {to}: {e}", exc_info=True)
        raise