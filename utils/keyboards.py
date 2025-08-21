from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Главное меню
main_menu_keyboard = ReplyKeyboardMarkup([
    ["📦 Отслеживание", "📄 Мои подписки"],
    ["🚆 Мои поезда", "📥 Получить базу"]
], resize_keyboard=True)

# Клавиатура выбора времени уведомлений
notify_time_keyboard = ReplyKeyboardMarkup([
    ["🕘 09:00", "🕓 16:00"],
    ["⏰ Указать время вручную"],
    ["🔙 Назад"]
], resize_keyboard=True, one_time_keyboard=True)

# Клавиатура подтверждения контейнеров
confirm_keyboard = ReplyKeyboardMarkup([
    ["✅ Да", "❌ Нет"]
], resize_keyboard=True, one_time_keyboard=True)

# Клавиатура отмены действия
cancel_keyboard = ReplyKeyboardMarkup([
    ["🔙 Назад"]
], resize_keyboard=True, one_time_keyboard=True)

# Клавиатура после выбора станции
dislocation_inline_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📄 Скачать список КТК", callback_data="download_ktk_list"),
        InlineKeyboardButton("📍 Актуальная дислокация", callback_data="get_dislocation_now")
    ]
])

# Клавиатура после выбора контейнеров
tracking_inline_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📍 Отслеживать в 09:00", callback_data="track_9"),
        InlineKeyboardButton("📍 Отслеживать в 16:00", callback_data="track_16")
    ],
    [
        InlineKeyboardButton("⏰ Выбрать своё время", callback_data="track_custom")
    ]
])
# Клавиатура подтверждения отмены отслеживания
cancel_tracking_confirm_keyboard = ReplyKeyboardMarkup([
    ["✅ Подтвердить отмену", "❌ Отмена"]
], resize_keyboard=True, one_time_keyboard=True)