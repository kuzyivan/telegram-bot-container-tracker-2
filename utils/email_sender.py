# utils/email_sender.py

import aiosmtplib
from email.message import EmailMessage

async def send_to_email(to_email, subject, text, file_bytes=None):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    if file_bytes:
        msg.add_attachment(
            file_bytes,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="report.xlsx"
        )
    # Настройка TLS/STARTTLS по порту
    smtp_kwargs = {
        "hostname": SMTP_HOST,
        "port": SMTP_PORT,
        "username": SMTP_USER,
        "password": SMTP_PASS,
    }
    if SMTP_PORT == 465:
        smtp_kwargs["use_tls"] = True
    else:  # 587 — STARTTLS для Яндекса и большинства провайдеров
        smtp_kwargs["start_tls"] = True
    await aiosmtplib.send(msg, **smtp_kwargs)
    logger.info(f"Письмо отправлено на {to_email} (тема: {subject})")