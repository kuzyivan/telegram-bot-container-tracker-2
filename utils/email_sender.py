import aiosmtplib
import asyncio
from email.message import EmailMessage
from dotenv import load_dotenv
import re
import time
import socket

from config import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, FROM_EMAIL
from logger import get_logger

from typing import Optional

logger = get_logger(__name__)
load_dotenv()

async def send_to_email(
    to_email: str,
    subject: str,
    text: str,
    attachment_bytes: Optional[bytes] = None,
    attachment_filename: str = "report.xlsx"
) -> bool:
    """
    Асинхронно отправляет письмо с вложением.
    Возвращает True при успехе, False при ошибке.
    """

    logger.info("[send_to_email] 🚀 Вызов функции send_to_email:")
    logger.info(f"[send_to_email] Параметры:\n  📧 to_email: {to_email}\n  📨 subject: {subject}\n  📎 attachment: {'есть' if attachment_bytes else 'нет'}")

    # Простая валидация e-mail
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", to_email):
        logger.warning(f"[send_to_email] ❌ Некорректный e-mail: {to_email}")
        return False

    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text, subtype="plain", charset="utf-8")

    if attachment_bytes:
        msg.add_attachment(
            attachment_bytes,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attachment_filename,
        )
        logger.info(f"[send_to_email] 📎 Прикреплён файл: {attachment_filename} (размер: {len(attachment_bytes)} байт)")

    # Определение DNS-имени сервера
    try:
        ip = socket.gethostbyname(SMTP_HOST)
        dns_name = socket.gethostbyaddr(ip)[0]
        logger.info(f"[send_to_email] 🔍 SMTP DNS: {SMTP_HOST} → {ip} ({dns_name})")
    except Exception as dns_err:
        logger.warning(f"[send_to_email] ⚠️ Ошибка при получении DNS-имени: {dns_err}")

    try:
        logger.info(f"[send_to_email] ⏳ Отправка письма через SMTP на {SMTP_HOST}:{SMTP_PORT}...")
        start_time = time.perf_counter()

        send_result = await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            use_tls=False,
            start_tls=True,
            timeout=20,
        )

        elapsed = time.perf_counter() - start_time
        logger.info(f"[send_to_email] ✅ Письмо успешно отправлено на {to_email} за {elapsed:.2f} сек")
        logger.info(f"[send_to_email] 📬 SMTP response: {send_result}")

        return True

    except Exception as e:
        logger.error(f"[send_to_email] ❌ Ошибка при отправке письма на {to_email}: {e}", exc_info=True)
        return False


# CLI-тест: python utils/email_sender.py your@email.com
if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(level=logging.INFO)

    to = sys.argv[1] if len(sys.argv) > 1 else SMTP_USER
    subject = "Тестовая email рассылка"
    body = "Это тестовое письмо. Всё работает!"
    logger.info("[CLI] 🚀 Тестовая отправка на email через __main__")
    result = asyncio.run(send_to_email(to, subject, body))
    if result:
        print("✅ Письмо успешно отправлено!")
    else:
        print("❌ Ошибка при отправке письма!")