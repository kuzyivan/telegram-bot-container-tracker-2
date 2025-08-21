# utils/keyboards.py
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

# === Главное меню (старый стиль, совместимо с user_handlers/misc_handlers) ===
# Кнопки: Дислокация / Задать слежение / Отмена слежения
reply_keyboard = ReplyKeyboardMarkup(
    [
        ["📦 Дислокация", "🔔 Задать слежение"],
        ["❌ Отмена слежения"],
    ],
    resize_keyboard=True
)

# === Альтернативное главное меню (если где-то используется main_menu_keyboard) ===
# Чтобы не плодить два разных меню, делаем его алиасом на reply_keyboard.
main_menu_keyboard = reply_keyboard

# === Клавиатура выбора времени уведомлений (Reply-кнопки) ===
notify_time_keyboard = ReplyKeyboardMarkup(
    [
        ["🕘 09:00", "🕓 16:00"],
        ["⏰ Указать время вручную"],
        ["🔙 Назад"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# === Клавиатура подтверждения выбора (если нужна где-то) ===
confirm_keyboard = ReplyKeyboardMarkup(
    [["✅ Да", "❌ Нет"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# === Клавиатура отмены действия (reply) ===
cancel_keyboard = ReplyKeyboardMarkup(
    [["🔙 Назад"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# === Инлайн-клавиатура после выбора станции (дислокация) ===
dislocation_inline_keyboard = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📄 Скачать список КТК", callback_data="download_ktk_list"),
            InlineKeyboardButton("📍 Актуальная дислокация", callback_data="get_dislocation_now"),
        ]
    ]
)

# === Инлайн-клавиатура после выбора контейнеров (быстрый выбор времени) ===
tracking_inline_keyboard = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📍 Отслеживать в 09:00", callback_data="track_9"),
            InlineKeyboardButton("📍 Отслеживать в 16:00", callback_data="track_16"),
        ],
        [
            InlineKeyboardButton("⏰ Выбрать своё время", callback_data="track_custom"),
        ],
    ]
)

# === Инлайн-клавиатура подтверждения отмены всех слежений ===
cancel_tracking_confirm_keyboard = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("✅ Да, отменить всё", callback_data="cancel_tracking_yes"),
            InlineKeyboardButton("❌ Нет", callback_data="cancel_tracking_no"),
        ]
    ]
)