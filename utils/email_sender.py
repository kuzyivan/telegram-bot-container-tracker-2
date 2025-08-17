import os
import asyncio
import smtplib
from email.message import EmailMessage
from logger import get_logger

logger = get_logger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

async def send_email(to, subject, body, attachments=None):
    """Отправляет письмо с возможными вложениями.

    Args:
        to (str): адрес получателя.
        subject (str): тема письма.
        body (str): тело письма.
        attachments (list[str], optional): пути к файлам для вложения.
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
            logger.error("Ошибка при добавлении вложения %s: %s", path, e, exc_info=True)

    async def _send():
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.send_message(message)
            logger.info("📧 Успешно отправлено письмо на %s", to)
        except Exception as e:
            logger.error("❌ Ошибка при отправке письма на %s: %s", to, e, exc_info=True)

    await asyncio.to_thread(_send)
