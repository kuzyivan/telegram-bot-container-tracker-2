import asyncio
import aiosmtplib
import re
from email.message import EmailMessage
from dotenv import load_dotenv
import time

from config import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, FROM_EMAIL
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

from typing import Optional

async def send_to_email(
    to_email: str,
    subject: str,
    text: str,
    attachment_bytes: Optional[bytes] = None,
    attachment_filename: str = "report.xlsx"
) -> bool:
    """
    Асинхронно отправляет письмо с вложением. Возвращает True при успехе, False при ошибке.
    """

    logger.info(f"[email_sender] ▶️ Запуск отправки письма на {to_email}")

    # Простая проверка e-mail
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", to_email):
        logger.warning(f"[email_sender] ❗️Некорректный адрес email: {to_email}")
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
        logger.info(f"[email_sender] 📎 Прикреплён файл: {attachment_filename}")

    try:
        logger.info(f"[email_sender] ⏳ Подключение к SMTP-серверу {SMTP_HOST}:{SMTP_PORT} как {SMTP_USER}")
        start_time = time.perf_counter()

        response = await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            use_tls=False,
            start_tls=True,
            timeout=30,
        )

        elapsed = time.perf_counter() - start_time
        logger.info(f"[email_sender] ✅ Письмо отправлено на {to_email} (за {elapsed:.2f} сек)")
        logger.debug(f"[email_sender] SMTP-ответ: {response}")
        return True

    except aiosmtplib.SMTPException as smtp_error:
        logger.error(f"[email_sender] ❌ SMTP ошибка при отправке письма на {to_email}: {smtp_error}", exc_info=True)
        return False
    except Exception as general_error:
        logger.error(f"[email_sender] ❌ Общая ошибка при отправке письма на {to_email}: {general_error}", exc_info=True)
        return False

# CLI тест (можно запускать: python email_sender.py your@email.com)
if __name__ == "__main__":
    import sys
    test_to = sys.argv[1] if len(sys.argv) > 1 else SMTP_USER
    test_subject = "✅ Тестовая рассылка"
    test_text = "Это тестовое письмо от трекинг-бота. Если ты это видишь — значит всё работает."
    
    logger.info("[email_sender] Запуск CLI-отправки")
    result = asyncio.run(send_to_email(test_to, test_subject, test_text))
    
    if result:
        print("✅ Письмо успешно отправлено!")
    else:
        print("❌ Ошибка при отправке письма!")