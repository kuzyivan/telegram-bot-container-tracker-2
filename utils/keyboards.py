# utils/keyboards.py
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from models import UserEmail # Импортируем модель UserEmail для типизации

# --- Reply Keyboards (появляются вместо обычной клавиатуры) ---

# Главное меню
main_menu_keyboard = ReplyKeyboardMarkup([
    ["📦 Отслеживание", "📄 Мои подписки"], # Можно заменить "Отслеживание" на "Дислокация", если так понятнее
    ["🚆 Мои поезда", "📥 Получить базу"], # "Получить базу" - возможно, стоит переименовать или убрать?
    ["⚙️ Настройки"] # Добавим кнопку Настроек
], resize_keyboard=True)

# Меню настроек
settings_menu_keyboard = ReplyKeyboardMarkup([
    ["📧 Управление Email", "📊 Статистика запросов"],
    ["🔙 Главное меню"]
], resize_keyboard=True)


# Клавиатура подтверждения (старая, возможно, больше не нужна)
confirm_keyboard = ReplyKeyboardMarkup([
    ["✅ Да", "❌ Нет"]
], resize_keyboard=True, one_time_keyboard=True)

# Клавиатура отмены/назад (старая, возможно, больше не нужна)
cancel_keyboard = ReplyKeyboardMarkup([
    ["🔙 Назад"]
], resize_keyboard=True, one_time_keyboard=True)


# --- Inline Keyboards (прикрепляются к сообщению) ---

def create_time_keyboard() -> InlineKeyboardMarkup:
    """Создает Inline клавиатуру для выбора времени уведомлений."""
    keyboard = [
        [
            InlineKeyboardButton("🕘 09:00", callback_data="time_09:00"),
            InlineKeyboardButton("🕓 16:00", callback_data="time_16:00")
        ],
        # Можно добавить больше стандартных времен или убрать кнопку ручного ввода, если она не нужна
        # [InlineKeyboardButton("⏰ Указать время вручную", callback_data="time_manual")] 
    ]
    return InlineKeyboardMarkup(keyboard)

def create_email_keyboard(emails: list[UserEmail], selected_ids: set[int] = None) -> InlineKeyboardMarkup:
    """
    Создает Inline клавиатуру для выбора Email адресов.
    Отмечает галочкой выбранные адреса.
    """
    if selected_ids is None:
        selected_ids = set()
        
    keyboard = []
    for email in emails:
        # Добавляем галочку к выбранным
        text = f"✅ {email.email}" if email.id in selected_ids else email.email
        keyboard.append([InlineKeyboardButton(text, callback_data=f"email_{email.id}")])
    
    # Добавляем кнопку подтверждения
    keyboard.append([InlineKeyboardButton("➡️ Подтвердить выбор", callback_data="confirm_emails")])
    return InlineKeyboardMarkup(keyboard)

# ✅ НОВАЯ ФУНКЦИЯ для Inline Да/Нет
def create_yes_no_inline_keyboard(yes_callback_data: str, no_callback_data: str) -> InlineKeyboardMarkup:
    """Создает Inline клавиатуру с кнопками Да и Нет."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да", callback_data=yes_callback_data),
            InlineKeyboardButton("❌ Нет", callback_data=no_callback_data)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Клавиатура подтверждения отмены отслеживания (пример использования новой функции)
def cancel_tracking_confirm_keyboard() -> InlineKeyboardMarkup:
     """Возвращает клавиатуру подтверждения отмены."""
     return create_yes_no_inline_keyboard(
         yes_callback_data="confirm_cancel_tracking_yes", 
         no_callback_data="confirm_cancel_tracking_no"
     )

# --- Старые клавиатуры (проверь, используются ли они еще) ---

# Клавиатура после выбора станции (возможно, устарела)
dislocation_inline_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📄 Скачать список КТК", callback_data="download_ktk_list"),
        InlineKeyboardButton("📍 Актуальная дислокация", callback_data="get_dislocation_now")
    ]
])

# Клавиатура после выбора контейнеров (возможно, устарела)
tracking_inline_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📍 Отслеживать в 09:00", callback_data="track_9"),
        InlineKeyboardButton("📍 Отслеживать в 16:00", callback_data="track_16")
    ],
    [
        InlineKeyboardButton("⏰ Выбрать своё время", callback_data="track_custom")
    ]
])