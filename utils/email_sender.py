import aiosmtplib
import asyncio
import logging
from email.message import EmailMessage
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from config import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, FROM_EMAIL

logger = logging.getLogger("email_sender")

async def send_to_email(
    to_email: str,
    subject: str,
    text: str,
    attachment_bytes: bytes = None,
    attachment_filename: str = "report.xlsx"
) -> bool:
    """Асинхронно отправляет письмо с вложением. Возвращает True при успехе, False при ошибке."""

    logger.info(f"[email_sender] Готовлюсь отправить письмо на {to_email} с темой '{subject}'")
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)

    if attachment_bytes:
        msg.add_attachment(
            attachment_bytes,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attachment_filename,
        )
        logger.info(f"[email_sender] Прикрепил файл {attachment_filename}")

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            use_tls=False,
            start_tls=True,
            timeout=20,
        )
        logger.info(f"[email_sender] ✅ Письмо отправлено на {to_email}")
        return True
    except Exception as e:
        logger.error(f"[email_sender] ❌ Ошибка при отправке письма на {to_email}: {e}", exc_info=True)
        return False

# Тест CLI: python email_sender.py your@email.com
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    to = sys.argv[1] if len(sys.argv) > 1 else SMTP_USER
    subject = "Тестовая email рассылка"
    body = "Это тестовое письмо. Всё работает!"
    logger.info(f"--- CLI ТЕСТ ---\nОтправка письма на {to}")
    result = asyncio.run(send_to_email(to, subject, body))
    if result:
        print("Письмо успешно отправлено!")
    else:
        print("Ошибка при отправке письма!")