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
    
    # 1. Определяем Subject и Body по умолчанию
    if subject is None:
         subject = "Дислокация контейнеров — отчет" # Более универсальная тема
    
    # 🚨 ИСПРАВЛЕНИЕ: Если body не задано, используем универсальный текст.
    if body is None:
        body = (
            "Привет! 👋\n\n"
            "Вы получили свежий отчёт о дислокации контейнеров.\n"
            "🔍 Проверьте вложение — там Excel-файл с актуальными данными.\n"
            "📭 Письмо сгенерировано автоматически.\n\n"
            "С заботой о логистике,\n"
            "Ваш контейнерный помощник 🤖"
        )
    
    # 2. Создание сообщения
    # Если to является списком, преобразуем его в строку через запятую для заголовка 'To'
    if isinstance(to, list):
         message_to = ", ".join(to)
    else:
         message_to = to
         
    message = EmailMessage()
    message["From"] = SMTP_USER
    message["To"] = message_to # Используем корректный заголовок
    message["Subject"] = subject
    
    # 3. Устанавливаем содержимое (теперь body гарантированно не None)
    message.set_content(body) 

    # 4. Добавляем вложения
    attachments = attachments or []
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
            # 🚨 ИСПРАВЛЕНИЕ: Вызываем generate_filename() только для создания имени файла
            filename = generate_filename() 
            message.add_attachment(
                data,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename,
            )
        except Exception as e:
            logger.error(f"❌ Ошибка при добавлении вложения {path}: {e}", exc_info=True)
            # Не бросаем исключение здесь, чтобы попытаться отправить письмо без проблемного вложения

    # 5. Основная отправка
    try:
        # SMTP-отладка может быть очень подробной, лучше включить ее только при необходимости: server.set_debuglevel(1)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            
            # 🚨 ИСПРАВЛЕНИЕ: send_message принимает to в виде списка
            recipient_list = to if isinstance(to, list) else [to]
            server.send_message(message, to_addrs=recipient_list)
            
        logger.info(f"📧 Успешно отправлено письмо на {message_to}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке письма на {message_to}: {e}", exc_info=True)
        # Оставляем raise, чтобы ошибка попала в лог Telegram
        raise
