# bot/handlers.py

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

# Импортируем бизнес-логику из 'core' и UI-элементы из 'ui'
from core.calculator import calculate_distance
from core.data_parser import search_station_names, normalize_station_name
from .ui import (
    MAIN_MENU_CHOICE, ASKING_FROM_STATION, ASKING_TO_STATION,
    BUTTON_DISTANCE_CALC, BUTTON_TARIFF_CALC
)

logger = logging.getLogger(__name__)

# --- Функции-обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отправляет приветственное сообщение с главным меню."""
    reply_keyboard = [[BUTTON_DISTANCE_CALC, BUTTON_TARIFF_CALC]]
    
    await update.message.reply_html(
        "Привет! Я бот для помощи в железнодорожных перевозках.\n\n"
        "<b>Выберите действие:</b>",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, resize_keyboard=True, input_field_placeholder="Выберите опцию из меню..."
        )
    )
    return MAIN_MENU_CHOICE

async def handle_main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор пользователя из Reply-меню."""
    text = update.message.text
    logger.info(f"Пользователь {update.effective_user.id} выбрал: '{text}'")

    if text == BUTTON_DISTANCE_CALC:
        await update.message.reply_html(
            "Отлично! <b>Введите станцию отправления:</b>\n"
            "Или используйте /cancel для отмены.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASKING_FROM_STATION
        
    elif text == BUTTON_TARIFF_CALC:
        await update.message.reply_text(
            "Эта функция находится в разработке. 👷‍♂️",
            reply_markup=ReplyKeyboardRemove()
        )
        return await start(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие, используя кнопки.")
        return MAIN_MENU_CHOICE

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выводит справочную информацию."""
    await update.message.reply_html(
        "<b>Как пользоваться ботом:</b>\n"
        "Используйте команду /start, чтобы открыть главное меню.\n\n"
        "<b>Команды:</b>\n"
        "  /start - Открыть главное меню\n"
        "  /cancel - Отменить текущий расчет\n\n"
        "При расчете расстояния я понимаю разные варианты написания станций (например, <i>Кунцево-2</i>, <i>Кунцево II</i>)."
    )

async def ask_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию отправления и запрашивает станцию назначения."""
    df_stations = context.bot_data['df_stations']
    station_a_raw = ""
    if update.message:
        station_a_raw = update.message.text.strip()
    elif update.callback_query:
        await update.callback_query.answer()
        station_a_raw = update.callback_query.data
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.callback_query.message.message_id)

    logger.info(f"Получена станция отправления: '{station_a_raw}'")

    normalized_a = normalize_station_name(station_a_raw)
    match_a = df_stations[df_stations['normalized_name'] == normalized_a]
    
    if match_a.empty:
        logger.warning(f"Станция '{station_a_raw}' не найдена. Предлагаю варианты.")
        similar = search_station_names(station_a_raw, df_stations, limit=5)
        if similar:
            keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in similar]
            reply_markup = InlineKeyboardMarkup(keyboard)
            response = (f"❌ Станция <b>'{station_a_raw}'</b> не найдена.\n"
                        f"Возможно, вы имели в виду один из этих вариантов?")
            await update.effective_message.reply_html(response, reply_markup=reply_markup)
        else:
            response = (f"❌ Станция <b>'{station_a_raw}'</b> не найдена.\n"
                        f"Проверьте написание и введите станцию отправления заново.")
            await update.effective_message.reply_html(response)
        return ASKING_FROM_STATION

    # --- ИЗМЕНЕНИЕ: Сохраняем всю информацию о станции ---
    station_info = match_a.iloc[0]
    context.user_data['from_station_info'] = {
        'name': station_info['station_name'],
        'code': station_info['station_code'],
        'railway': station_info['railway']
    }
    # ----------------------------------------------------

    await update.effective_message.reply_html(
        f"✅ Станция отправления: <b>{station_info['station_name']}</b>\n"
        f"<code>({station_info['station_code']}, {station_info['railway']})</code>\n\n"
        "<b>Теперь введите станцию назначения:</b>"
    )
    return ASKING_TO_STATION

async def ask_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию назначения и выполняет расчет."""
    df_stations = context.bot_data['df_stations']
    transit_matrices = context.bot_data['transit_matrices']
    station_b_raw = ""
    if update.message:
        station_b_raw = update.message.text.strip()
    elif update.callback_query:
        await update.callback_query.answer()
        station_b_raw = update.callback_query.data
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.callback_query.message.message_id)

    logger.info(f"Получена станция назначения: '{station_b_raw}'")

    normalized_b = normalize_station_name(station_b_raw)
    match_b = df_stations[df_stations['normalized_name'] == normalized_b]

    if match_b.empty:
        logger.warning(f"Станция '{station_b_raw}' не найдена. Предлагаю варианты.")
        similar = search_station_names(station_b_raw, df_stations, limit=5)
        if similar:
            keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in similar]
            reply_markup = InlineKeyboardMarkup(keyboard)
            response = (f"❌ Станция <b>'{station_b_raw}'</b> не найдена.\n"
                        f"Возможно, вы имели в виду один из этих вариантов?")
            await update.effective_message.reply_html(response, reply_markup=reply_markup)
        else:
            response = (f"❌ Станция <b>'{station_b_raw}'</b> не найдена.\n"
                        f"Введите станцию назначения заново.")
            await update.effective_message.reply_html(response)
        return ASKING_TO_STATION

    # --- ИЗМЕНЕНИЕ: Получаем всю информацию о станции ---
    from_station_info = context.user_data['from_station_info']
    to_station_info = {
        'name': match_b.iloc[0]['station_name'],
        'code': match_b.iloc[0]['station_code'],
        'railway': match_b.iloc[0]['railway']
    }
    # ----------------------------------------------------
    
    await update.effective_message.reply_html(
        f"✅ Станция назначения: <b>{to_station_info['name']}</b>\n"
        f"<code>({to_station_info['code']}, {to_station_info['railway']})</code>\n\n"
        f"Ищу маршрут..."
    )
    logger.info(f"Начинаю расчет для '{from_station_info['name']}' -> '{to_station_info['name']}'")

    result = calculate_distance(from_station_info['name'], to_station_info['name'], df_stations, transit_matrices)
    logger.info(f"Результат функции calculate_distance: {result['status']}")

    if result['status'] == 'success':
        route = result['route']
        if route.get('is_same_station'):
            response = (f"✅ Станция отправления и назначения совпадают: <b>{from_station_info['name']}</b>.\n"
                        f"Расстояние: <b>{route['total_distance']} км</b>.")
        else:
            # --- ИЗМЕНЕНИЕ: Форматируем итоговый ответ ---
            response = (
                f"✅ Маршрут рассчитан:\n\n"
                f"<b>Отправление:</b>\n"
                f"<code>{from_station_info['name']} ({from_station_info['code']}, {from_station_info['railway']})</code>\n\n"
                f"<b>Назначение:</b>\n"
                f"<code>{to_station_info['name']} ({to_station_info['code']}, {to_station_info['railway']})</code>\n\n"
                f"------------------------------\n"
                f"1. {route['from']} → {route['tpa_name']}: {route['distance_a_to_tpa']} км\n"
                f"2. {route['tpa_name']} → {route['tpb_name']}: {route['distance_tpa_to_tpb']} км\n"
                f"3. {route['tpb_name']} → {route['to']}: {route['distance_tpb_to_b']} км\n"
                f"------------------------------\n"
                f"<b>ИТОГОВОЕ ТАРИФНОЕ РАССТОЯНИЕ: {route['total_distance']} км</b>"
            )
            # --------------------------------------------
        logger.info(f"Маршрут успешно рассчитан.")
    else:
        response = f"❌ Ошибка расчета: {result['message']}"
        logger.error(f"Ошибка при расчете маршрута: {result['message']}.")

    await update.effective_message.reply_html(response)
    context.user_data.clear()

    reply_keyboard = [[BUTTON_DISTANCE_CALC, BUTTON_TARIFF_CALC]]
    await update.effective_message.reply_html(
        "------------------------------\n"
        "<b>Выберите следующее действие:</b>",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, resize_keyboard=True, input_field_placeholder="Выберите опцию из меню..."
        )
    )
    return MAIN_MENU_CHOICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет текущий диалог и возвращает в главное меню."""
    logger.info(f"Пользователь {update.effective_user.id} отменил диалог.")
    context.user_data.clear()
    
    # Убираем инлайн-клавиатуру, если она была
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Расчет отменен.")
    
    await update.effective_message.reply_text(
        "Расчет отменен.",
        reply_markup=ReplyKeyboardRemove()
    )
    return await start(update, context)