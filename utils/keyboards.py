from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Reply-клавиатура (всегда снизу)
reply_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📦 Дислокация")],
        [KeyboardButton("🔔 Задать слежение")],
    ],
    resize_keyboard=True
)

# Inline-клавиатуры для дальнейших действий
dislocation_inline_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Ввести контейнер", callback_data="dislocation_inline")]
])
tracking_inline_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Ввести контейнер(ы)", callback_data="track_request")]
])

# Для старого main_menu_keyboard — можешь оставить если используется где-то ещё
main_menu_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚀 Старт", callback_data='start')],
    [InlineKeyboardButton("📦 Дислокация", callback_data='dislocation')],
    [InlineKeyboardButton("🔔 Задать слежение", callback_data='track_request')],
])
# Универсальная клавиатура для меню
universal_menu_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Главное меню", callback_data='start')],
    [InlineKeyboardButton("Назад", callback_data='back')]
])
# Универсальная клавиатура для меню с кнопкой "Назад"
universal_menu_keyboard_with_back = InlineKeyboardMarkup([
    [InlineKeyboardButton("Главное меню", callback_data='start')],
    [InlineKeyboardButton("Назад", callback_data='back')]
])