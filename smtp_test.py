import os
import smtplib
from dotenv import load_dotenv
load_dotenv()
# остальной код как выше

# Берём переменные из окружения
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
TO_EMAIL = os.getenv("TO_EMAIL", "i.kuzmenko@aterminal.pro")  # Для теста

server = smtplib.SMTP('smtp.yandex.ru', 587)
server.set_debuglevel(1)
server.starttls()
server.login(SMTP_USER, SMTP_PASS)
server.sendmail(FROM_EMAIL, TO_EMAIL, 'Subject: test\n\nhello')
server.quit()
print('OK! Письмо отправлено на', TO_EMAIL)