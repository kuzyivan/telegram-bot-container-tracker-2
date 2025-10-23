# utils/email_sender.py
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

def generate_verification_email(code: str, telegram_id: int) -> tuple[str, str]:
    """Генерирует тему и тело письма с кодом подтверждения."""
    subject = f"Код подтверждения для AtermTrackBot: {code}"
    body = (
        f"Здравствуйте! 👋\n\n"
        f"Вы запросили подтверждение email-адреса для пользователя Telegram ID: {telegram_id}.\n\n"
        f"Ваш код подтверждения:\n\n"
        f"***{code}***\n\n"
        f"Пожалуйста, введите этот код в чате с ботом в течение 10 минут.\n\n"
        f"С уважением,\n"
        f"Ваш контейнерный помощник 🤖"
    )
    return subject, body

# --- ИСПРАВЛЕНИЕ: Удалено 'async' ---
def send_email(to, subject=None, body=None, attachments=None):
    """
    Отправляет письмо с вложениями или простое текстовое письмо.
    
    Эта функция СИНХРОННА. Она должна вызываться через asyncio.to_thread().
    """
    # Если это письмо с кодом, subject и body будут заполнены
    if subject is None and body is None and not attachments:
        subject = "Дислокация контейнеров — отправка от ООО «Терминал»"
        body = (
            "Привет! 👋\n\n"
            "Вы получили свежий отчёт о дислокации контейнеров.\n"
            "Письмо автоматически отправлено нашим ботом, пока вы занимаетесь делами посерьёзнее 😎\n\n"
            "🔍 Проверьте вложение — там Excel-файл с актуальными данными.\n"
            "📭 Письмо сгенерировано автоматически. Если возникнут вопросы, напишите на почту клиентского сервиса: oks@aterminal.pro\n\n"
            "С заботой о логистике,\n"
            "Ваш контейнерный помощник 🤖\n"
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
        # Оставляем raise, чтобы вы видели ошибку, но можно убрать, если она не критична для работы
        raise
