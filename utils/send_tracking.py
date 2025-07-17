import io
import re
import pandas as pd
import aiosmtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from openpyxl.styles import PatternFill
from tenacity import retry, stop_after_attempt, wait_exponential
from config import SMTP_USER, SMTP_PASS, SMTP_HOST, SMTP_PORT, FROM_EMAIL
from logger import get_logger

logger = get_logger(__name__)
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


def get_vladivostok_filename(prefix="Слежение контейнеров"):
    vladivostok_time = datetime.utcnow() + timedelta(hours=10)
    return f"{prefix} {vladivostok_time.strftime('%H-%M')}.xlsx"


def clean_sheet_name(name: str) -> str:
    return re.sub(r"[:\\/?*\[\]']", "_", str(name))[:31]


def generate_excel_report(rows, columns) -> bytes:
    logger.info("Генерация Excel-файла в байтах")
    try:
        df = pd.DataFrame(rows, columns=columns)
        with io.BytesIO() as output:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Экспорт')
                worksheet = writer.sheets['Экспорт']
                header_fill = PatternFill(start_color='87CEEB', end_color='87CEEB', fill_type='solid')
                for cell in worksheet[1]:
                    cell.fill = header_fill
                for col in worksheet.columns:
                    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
                    worksheet.column_dimensions[col[0].column_letter].width = max_length + 2
            output.seek(0)
            return output.read()
    except Exception as e:
        logger.error("Ошибка при генерации Excel-файла: %s", e, exc_info=True)
        raise


class EmailSender:
    def __init__(self,
                 smtp_host: str = SMTP_HOST,
                 smtp_port: int = SMTP_PORT,
                 smtp_user: str = SMTP_USER,
                 smtp_pass: str = SMTP_PASS,
                 from_email: str = FROM_EMAIL):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_email = from_email

    @staticmethod
    def _sanitize_header(value: str) -> str:
        return re.sub(r'[\r\n]', '', value)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
    async def send_email(
        self,
        to_email: str,
        subject: str,
        text: str,
        attachment_bytes: bytes = None,
        attachment_filename: str = "tracking_report.xlsx"
    ):
        if not isinstance(to_email, str) or '@' not in to_email:
            raise ValueError("Некорректный email получателя")

        msg = EmailMessage()
        msg["From"] = self._sanitize_header(self.from_email)
        msg["To"] = self._sanitize_header(to_email)
        msg["Subject"] = self._sanitize_header(subject)
        msg.set_content(text, charset="utf-8")

        if attachment_bytes:
            if len(attachment_bytes) > MAX_ATTACHMENT_SIZE:
                raise ValueError("Превышен допустимый размер вложения")
            msg.add_attachment(
                attachment_bytes,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=attachment_filename
            )

        try:
            await aiosmtplib.send(
                message=msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_pass,
                start_tls=self.smtp_port != 465,
                timeout=10
            )
            logger.info(f"📧 Письмо отправлено на {to_email}")
        except Exception as e:
            safe_err = str(e).replace(self.smtp_pass, "***")
            logger.error(f"❌ Ошибка отправки письма на {to_email}: {safe_err}")
            raise