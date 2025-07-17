import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
TO_EMAIL = os.getenv("TO_EMAIL", "i.kuzmenko@aterminal.pro")

msg = EmailMessage()
msg["Subject"] = "test"
msg["From"] = FROM_EMAIL
msg["To"] = TO_EMAIL
msg.set_content("hello")

server = smtplib.SMTP('smtp.yandex.ru', 587)
server.set_debuglevel(1)
server.starttls()
server.login(SMTP_USER, SMTP_PASS)
server.send_message(msg)
server.quit()

print('OK! Письмо отправлено на', TO_EMAIL)