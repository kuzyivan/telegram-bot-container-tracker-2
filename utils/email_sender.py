import os
import smtplib
from email.message import EmailMessage
from logger import get_logger
from datetime import datetime

logger = get_logger(__name__)

# SMTP-настройки из .env
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

def generate_filename():
    """
    Генерирует красивое имя для Excel-файла, например:
    Dislocation_Report_19-08-2025_15-00.xlsx
    """
    now = datetime.now().strftime("%d-%m-%Y_%H-%M")
    return f"Dislocation_Report_{now}.xlsx"

async def send_email(to, subject=None, body=None, attachments=None):
    """
    Отправляет письмо с вложениями.

    Args:
        to (str): email-адрес получателя
        subject (str): тема письма (по умолчанию фиксированная)
        body (str): тело письма (по умолчанию фиксированное)
        attachments (list[str]): пути к Excel-файлам
    """
    subject = subject or "Дислокация контейнеров — отправка от ООО «Терминал»"
    body = body or (
        "Привет! 👋\n\n"
        "Ты получил свежий отчёт по дислокации контейнеров.\n"
        "Всё автоматически собрано, отсортировано и отправлено нашим ботом, пока ты занимаешься делами посерьёзнее 😎\n\n"
        "🔍 Проверь вложение — там Excel-файл с актуальными данными.\n"
        "📭 Письмо сгенерировано автоматически. Если возникнут вопросы, напиши на почту клиентского сервиса: oks@aterminal.pro\n\n"
        "С заботой о логистике,\n"
        "Твой контейнерный помощник 🤖\n"
        "ООО «Терминал»"
    )

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
            filename = generate_filename()
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
            server.set_debuglevel(1)  # SMTP debug trace
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(message)
        logger.info(f"📧 Успешно отправлено письмо на {to}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке письма на {to}: {e}", exc_info=True)
        raise