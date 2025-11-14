# utils/telegram_text_utils.py
import re

def escape_markdown(text: str) -> str:
    """
    Escapes characters for Telegram's legacy Markdown parse mode.
    """
    if not text:
        return ""
    # Characters to escape are: _, *, `, [
    return re.sub(r'([_*`\[])', r'\\\1', text)