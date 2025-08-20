from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)

# Главное меню (reply-клавиатура)
reply_keyboard = ReplyKeyboardMarkup(
    [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"]
    ],
    resize_keyboard=True
)

# Inline клавиатура главного меню
main_menu_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📦 Дислокация", callback_data="dislocation")],
    [InlineKeyboardButton("🔔 Задать слежение", callback_data="track_request")],
])

# Inline клавиатура подтверждения удаления отслеживания
tracking_inline_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Удалить все", callback_data="cancel_tracking_all")],
    [InlineKeyboardButton("Оставить как есть", callback_data="cancel_tracking_cancel")]
])

# Клавиатура для выбора времени уведомлений
tracking_time_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("09:00", callback_data="time_09_00"),
        InlineKeyboardButton("16:00", callback_data="time_16_00"),
    ],
    [InlineKeyboardButton("Ввести своё время", callback_data="time_custom")]
])

# Inline клавиатура после выбора контейнера
dislocation_inline_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📦 Посмотреть дислокацию", callback_data="dislocation_inline")]
])