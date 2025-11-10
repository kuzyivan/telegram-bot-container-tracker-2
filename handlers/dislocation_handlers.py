# handlers/distance_handlers.py
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
# ИСПРАВЛЕНИЕ: Импортируем обе функции
from services.tariff_service import get_tariff_distance, find_stations_by_name
from logger import get_logger
import html

logger = get_logger(__name__)

# --- НОВЫЕ Состояния диалога ---
ASK_FROM_STATION, RESOLVE_FROM_STATION, ASK_TO_STATION, RESOLVE_TO_STATION = range(4)

# --- Вспомогательная функция для создания кнопок ---
def build_station_keyboard(stations: list[dict], callback_prefix: str) -> InlineKeyboardMarkup:
    keyboard = []
    for station in stations[:10]: # Ограничиваем 10 вариантами
        # Сохраняем ТОЛЬКО имя в callback_data, чтобы избежать проблем с длиной
        callback_data = f"{callback_prefix}_{station['name']}"
        display_text = f"{station['name']} ({station.get('railway', 'Н/Д')})"
        keyboard.append([InlineKeyboardButton(display_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="distance_cancel")])
    return InlineKeyboardMarkup(keyboard)

# --- Точка входа /distance ---
async def distance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(
        "Пожалуйста, введите **станцию отправления** (например, 'Хабаровск')."
        "\nИли введите /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    context.user_data.clear()
    return ASK_FROM_STATION

# --- Шаг 1: Получаем станцию ОТПРАВЛЕНИЯ ---
async def process_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END

    from_station_raw = update.message.text.strip()

    matches = await find_stations_by_name(from_station_raw)

    if not matches:
        await update.message.reply_text(f"❌ Станция '{from_station_raw}' не найдена. Попробуйте еще раз или /cancel.")
        return ASK_FROM_STATION

    if len(matches) == 1:
        station = matches[0]
        context.user_data['from_station_name'] = station['name'] # Сохраняем точное имя
        await update.message.reply_text(
            f"✅ Станция отправления: <b>{station['name']}</b>\n"
            f"Теперь введите <b>станцию назначения</b>.",
            parse_mode='HTML'
        )
        return ASK_TO_STATION

    if len(matches) > 1:
        context.user_data['ambiguous_stations'] = matches
        keyboard = build_station_keyboard(matches, "dist_from")
        await update.message.reply_text(
            f"⚠️ Найдено несколько станций по запросу '{from_station_raw}'.\n"
            "Пожалуйста, уточните станцию **отправления**:",
            reply_markup=keyboard
        )
        return RESOLVE_FROM_STATION

    return ASK_FROM_STATION

# --- Шаг 2: Уточняем станцию ОТПРАВЛЕНИЯ (если нужно) ---
async def resolve_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not query.data or not context.user_data:
         return ConversationHandler.END

    chosen_name = query.data.replace("dist_from_", "")

    context.user_data['from_station_name'] = chosen_name

    await query.edit_message_text(
        f"✅ Станция отправления: <b>{chosen_name}</b>\n"
        f"Теперь введите <b>станцию назначения</b>.",
        parse_mode='HTML'
    )
    return ASK_TO_STATION

# --- Шаг 3: Получаем станцию НАЗНАЧЕНИЯ ---
async def process_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (not update.message or not update.message.text or 
        not context.user_data or 'from_station_name' not in context.user_data):
        return ConversationHandler.END

    to_station_raw = update.message.text.strip()
    matches = await find_stations_by_name(to_station_raw)

    if not matches:
        await update.message.reply_text(f"❌ Станция '{to_station_raw}' не найдена. Попробуйте еще раз или /cancel.")
        return ASK_TO_STATION

    if len(matches) == 1:
        station = matches[0]
        context.user_data['to_station_name'] = station['name']
        # Обе станции известны, запускаем расчет
        return await run_distance_calculation(update, context)

    if len(matches) > 1:
        context.user_data['ambiguous_stations'] = matches
        keyboard = build_station_keyboard(matches, "dist_to")
        await update.message.reply_text(
            f"⚠️ Найдено несколько станций по запросу '{to_station_raw}'.\n"
            "Пожалуйста, уточните станцию **назначения**:",
            reply_markup=keyboard
        )
        return RESOLVE_TO_STATION

    return ASK_TO_STATION

# --- Шаг 4: Уточняем станцию НАЗНАЧЕНИЯ (если нужно) ---
async def resolve_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not query.data or not context.user_data:
         return ConversationHandler.END

    chosen_name = query.data.replace("dist_to_", "")
    context.user_data['to_station_name'] = chosen_name

    # Обе станции известны, запускаем расчет
    return await run_distance_calculation(update, context)

# --- Шаг 5: Выполняем расчет ---
async def run_distance_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_to_reply = update.message or update.callback_query.message

    from_station_name = context.user_data.get('from_station_name')
    to_station_name = context.user_data.get('to_station_name')

    if not from_station_name or not to_station_name:
        await message_to_reply.reply_text("❌ Ошибка: одна из станций не выбрана. Начните заново /distance.")
        return ConversationHandler.END

    await message_to_reply.reply_text("⏳ Выполняю расчет тарифного расстояния...")

    try:
        result = await get_tariff_distance(
            from_station_name=from_station_name,
            to_station_name=to_station_name
        )

        if result:
            distance = result['distance']
            info_a = result['info_a']
            info_b = result['info_b']

            response = (
                f"✅ <b>Расчет успешно выполнен!</b>\n\n"
                f"🚉 <b>Отправление:</b>\n"
                f"<b>{html.escape(info_a['station_name'])}</b> <i>({html.escape(info_a.get('railway', 'Н/Д'))})</i>\n\n"
                f"🏁 <b>Назначение:</b>\n"
                f"<b>{html.escape(info_b['station_name'])}</b> <i>({html.escape(info_b.get('railway', 'Н/Д'))})</i>\n\n"
                f"————————————————\n"
                f"🛤️ <b>Тарифное расстояние: {distance} км</b>"
            )

            await message_to_reply.reply_text(response, parse_mode='HTML')
        else:
            response = (
                f"❌ <b>Не удалось найти маршрут.</b>\n"
                f"Не найден путь в матрицах между:\n"
                f"<code>{html.escape(from_station_name)}</code> ➡️ <code>{html.escape(to_station_name)}</code>"
            )
            await message_to_reply.reply_text(response, parse_mode='HTML')

    except Exception as e:
        logger.exception(f"Критическая ошибка в /distance (run_distance_calculation): {e}")
        await message_to_reply.reply_text(f"❌ Произошла внутренняя ошибка: {e}", parse_mode='HTML')

    context.user_data.clear()
    return ConversationHandler.END

# --- Обработка отмены ---
async def cancel_distance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_to_reply = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()

    await message_to_reply.reply_text("Расчет расстояния отменён.", reply_markup=ReplyKeyboardRemove())
    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

# --- Регистрация хендлеров ---
def distance_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("distance", distance_cmd)],
        states={
            ASK_FROM_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_from_station)],
            RESOLVE_FROM_STATION: [CallbackQueryHandler(resolve_from_station, pattern="^dist_from_")],
            ASK_TO_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_to_station)],
            RESOLVE_TO_STATION: [CallbackQueryHandler(resolve_to_station, pattern="^dist_to_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_distance),
            CallbackQueryHandler(cancel_distance, pattern="^distance_cancel$")
        ],
        allow_reentry=True,
    )