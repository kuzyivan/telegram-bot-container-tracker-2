# keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

main_menu_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚀 Старт", callback_data='start')],
    [InlineKeyboardButton("📦 Дислокация", callback_data='dislocation')],
    [InlineKeyboardButton("🔔 Задать слежение", callback_data='track_request')],
])
