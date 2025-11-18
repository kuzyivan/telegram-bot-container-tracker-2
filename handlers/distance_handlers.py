# handlers/distance_handlers.py
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ApplicationHandlerStop,
)
from typing import Optional
from services.tariff_service import get_tariff_distance, find_stations_by_name
from logger import get_logger
import html

logger = get_logger(__name__)

# --- Состояния диалога ---
ASK_FROM_STATION, RESOLVE_FROM_STATION, ASK_TO_STATION, RESOLVE_TO_STATION = range(4)

# --- Вспомогательная функция для создания кнопок ---
def build_station_keyboard(stations: list[dict], callback_prefix: str) -> InlineKeyboardMarkup:
    keyboard = []
    for station in stations[:10]: # Ограничиваем 10 вариантами
        # Используем безопасный доступ к полям
        railway_display = station.get('railway', 'Н/Д')
        code_display = station.get('code', '')
        
        callback_data = f"{callback_prefix}_{station['name']}"
        display_text = f"{station['name']} ({railway_display})"
        keyboard.append([InlineKeyboardButton(display_text, callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="distance_cancel")])
    return InlineKeyboardMarkup(keyboard)

# --- Точка входа /distance ---
async def distance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: /distance command received. Starting conversation.")
    
    if not update.message:
        logger.warning(f"[Dist] User {user_id}: /distance called without a message. Ending.")
        return ConversationHandler.END

    if context.user_data is not None:
        context.user_data.clear()
        context.user_data['is_distance_active'] = True

    await update.message.reply_text(
        "Пожалуйста, введите **станцию отправления** (например, 'Хабаровск')."
        "\nИли введите /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return ASK_FROM_STATION

# --- Шаг 1: Получаем станцию ОТПРАВЛЕНИЯ ---
async def process_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Now in ASK_FROM_STATION.")

    if not update.message or not update.message.text:
        if update.callback_query:
             await update.callback_query.answer("Пожалуйста, введите название текстом.")
        return ASK_FROM_STATION 

    from_station_raw = update.message.text.strip()
    logger.info(f"[Dist] User {user_id}: Received 'from_station': {from_station_raw}. Calling find_stations_by_name.")

    try:
        matches = await find_stations_by_name(from_station_raw)
        logger.info(f"[Dist] User {user_id}: find_stations_by_name found {len(matches)} matches for 'from_station'.")
    except Exception as e:
        logger.error(f"[Dist] User {user_id}: CRITICAL FAILURE in find_stations_by_name for '{from_station_raw}': {e}", exc_info=True)
        await update.message.reply_text(f"❌ Произошла внутренняя ошибка при поиске станции: {e}")
        return ConversationHandler.END

    if not matches:
        await update.message.reply_text(f"❌ Станция '{from_station_raw}' не найдена. Попробуйте еще раз или /cancel.")
        return ASK_FROM_STATION

    if len(matches) == 1:
        station = matches[0]
        
        if context.user_data is not None:
            context.user_data['from_station_name'] = station['name'] 
        
        logger.info(f"[Dist] User {user_id}: Single match found: {station['name']}. Moving to ASK_TO_STATION.")
        
        # Безопасный вывод
        code_display = html.escape(station.get('code', 'н/д'))
        railway_display = html.escape(station.get('railway', 'н/д'))
        
        await update.message.reply_text(
            f"✅ Станция отправления: <b>{html.escape(station['name'])}</b> "
            f"(`{code_display}, {railway_display}`)\n"
            f"Теперь введите <b>станцию назначения</b>.",
            parse_mode='HTML'
        )
        return ASK_TO_STATION

    if len(matches) > 1:
        
        if context.user_data is not None:
            context.user_data['ambiguous_stations'] = matches
        
        keyboard = build_station_keyboard(matches, "dist_from")
        logger.info(f"[Dist] User {user_id}: Multiple matches found. Moving to RESOLVE_FROM_STATION.")
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
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Now in RESOLVE_FROM_STATION.")
    
    if not query or not query.data or not query.message: 
        if query: await query.answer()
        return ConversationHandler.END
        
    await query.answer() 

    chosen_name = query.data.replace("dist_from_", "") 
    
    if context.user_data:
        context.user_data['from_station_name'] = chosen_name
    
    logger.info(f"[Dist] User {user_id}: Resolved 'from_station' to {chosen_name}. Moving to ASK_TO_STATION.")
    
    # Пытаемся найти полные данные для вывода (хотя бы из кэша matches)
    station_info = next((s for s in context.user_data.get('ambiguous_stations', []) if s.get('name') == chosen_name), {})
    code_display = html.escape(station_info.get('code', 'н/д'))
    railway_display = html.escape(station_info.get('railway', 'н/д'))

    await query.edit_message_text( 
        f"✅ Станция отправления: <b>{html.escape(chosen_name)}</b> "
        f"(`{code_display}, {railway_display}`)\n"
        f"Теперь введите <b>станцию назначения</b>.",
        parse_mode='HTML'
    )
    return ASK_TO_STATION

# --- Шаг 3: Получаем станцию НАЗНАЧЕНИЯ ---
async def process_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Now in ASK_TO_STATION.")
    
    if (not update.message or not update.message.text or 
        not context.user_data or 'from_station_name' not in context.user_data):
        logger.warning(f"[Dist] User {user_id}: Exiting ASK_TO_STATION (invalid state).")
        return ConversationHandler.END

    to_station_raw = update.message.text.strip()
    logger.info(f"[Dist] User {user_id}: Received 'to_station': {to_station_raw}. Calling find_stations_by_name.")

    try:
        matches = await find_stations_by_name(to_station_raw) 
        logger.info(f"[Dist] User {user_id}: find_stations_by_name found {len(matches)} matches for 'to_station'.")
    except Exception as e:
        logger.error(f"[Dist] User {user_id}: CRITICAL FAILURE in find_stations_by_name for '{to_station_raw}': {e}", exc_info=True)
        await update.message.reply_text(f"❌ Произошла внутренняя ошибка при поиске станции: {e}")
        return ConversationHandler.END

    if not matches:
        await update.message.reply_text(f"❌ Станция '{to_station_raw}' не найдена. Попробуйте еще раз или /cancel.")
        return ASK_TO_STATION

    if len(matches) == 1:
        station = matches[0]
        if context.user_data is not None:
            context.user_data['to_station_name'] = station['name']
        logger.info(f"[Dist] User {user_id}: Single match found: {station['name']}. Moving to run_distance_calculation.")
        return await run_distance_calculation(update, context)

    if len(matches) > 1:
        if context.user_data is not None:
            context.user_data['ambiguous_stations'] = matches
        keyboard = build_station_keyboard(matches, "dist_to")
        logger.info(f"[Dist] User {user_id}: Multiple matches found. Moving to RESOLVE_TO_STATION.")
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
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Now in RESOLVE_TO_STATION.")
    
    if not query or not query.data: 
        if query: await query.answer()
        return ConversationHandler.END
        
    await query.answer() 

    chosen_name = query.data.replace("dist_to_", "") 
    
    if context.user_data:
        context.user_data['to_station_name'] = chosen_name
    
    logger.info(f"[Dist] User {user_id}: Resolved 'to_station' to {chosen_name}. Moving to run_distance_calculation.")

    return await run_distance_calculation(update, context)

# --- Шаг 5: Выполняем расчет (ОБНОВЛЕНО ДЛЯ ДЕТАЛИЗАЦИИ ТП) ---
async def run_distance_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Now in run_distance_calculation.")

    query = update.callback_query
    message = update.message

    message_to_reply: Optional[Message] = None
    if isinstance(message, Message):
        message_to_reply = message
    elif query and isinstance(query.message, Message):
        message_to_reply = query.message

    if not message_to_reply: 
        logger.error(f"[Dist] User {user_id}: Could not find message to reply to in run_distance_calculation. Ending.")
        return ConversationHandler.END

    assert message_to_reply is not None

    from_station_name = context.user_data.get('from_station_name') if context.user_data else None 
    to_station_name = context.user_data.get('to_station_name') if context.user_data else None 

    if not from_station_name or not to_station_name:
        logger.warning(f"[Dist] User {user_id}: Exiting calculation (from_station or to_station missing).")
        await message_to_reply.reply_text("❌ Ошибка: одна из станций не выбрана. Начните заново /distance.") 
        return ConversationHandler.END
    
    logger.info(f"[Dist] User {user_id}: Calculating distance for: {from_station_name} -> {to_station_name}.")

    if query:
        await query.edit_message_text(
            f"✅ Станция отправления: <b>{html.escape(from_station_name)}</b>\n"
            f"✅ Станция назначения: <b>{html.escape(to_station_name)}</b>\n\n"
            f"⏳ Выполняю расчет...",
            parse_mode='HTML'
        )
    else:
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
            route = result['route_details'] # ✅ ИЗВЛЕКАЕМ ДЕТАЛИ МАРШРУТА
            
            # --- БЕЗОПАСНЫЙ ДОСТУП К ДАННЫМ СТАНЦИЙ ДЛЯ ВЫВОДА ---
            from_station_display = f"{html.escape(info_a.get('station_name', from_station_name))} (`{html.escape(info_a.get('code', 'н/д'))}, {html.escape(info_a.get('railway', 'Н/Д'))}`)"
            to_station_display = f"{html.escape(info_b.get('station_name', to_station_name))} (`{html.escape(info_b.get('code', 'н/д'))}, {html.escape(info_b.get('railway', 'Н/Д'))}`)"
            
            # Определяем, был ли маршрут прямым (TP A == TP B)
            is_direct = route['tpa_name'] == route['tpb_name']
            
            response = (
                f"✅ **Маршрут рассчитан:**\n\n"
                f"**Отправление:**\n"
                f"{from_station_display}\n\n"
                f"**Назначение:**\n"
                f"{to_station_display}\n\n"
                f"**————————————————**\n"
                f"**Детализация маршрута:**\n"
            )
            
            # Вывод деталей маршрута
            if is_direct:
                 response += f"1. {html.escape(route['tpa_name'])} → {html.escape(route['tpb_name'])}: {distance} км\n"
            else:
                response += (
                    # Шаг 1: Отправление -> ТП A
                    f"1. {html.escape(info_a.get('station_name', from_station_name))} → **{html.escape(route['tpa_name'])}** (ТП): {route['distance_a_to_tpa']} км\n"
                    # Шаг 2: ТП A -> ТП B
                    f"2. **{html.escape(route['tpa_name'])}** → **{html.escape(route['tpb_name'])}** (ТП): {route['distance_tpa_to_tpb']} км\n"
                    # Шаг 3: ТП B -> Назначение
                    f"3. **{html.escape(route['tpb_name'])}** → {html.escape(info_b.get('station_name', to_station_name))}: {route['distance_tpb_to_b']} км\n"
                )
            
            response += f"**————————————————**\n"
            response += f"**ИТОГОВОЕ ТАРИФНОЕ РАССТОЯНИЕ: {distance} км**"
            
            if query:
                # Удаляем "выполняю расчет..."
                await query.delete_message()
            
            await message_to_reply.reply_text(response, parse_mode='Markdown')

        else:
            logger.warning(f"[Dist] User {user_id}: Calculation FAILED (route not found in matrix) for {from_station_name} -> {to_station_name}.")
            response = (
                f"❌ **Не удалось найти маршрут.**\n"
                f"Проверьте правильность написания станций и убедитесь, что маршрут присутствует в тарифной базе."
            )
            await message_to_reply.reply_text(response, parse_mode='Markdown') 

    except Exception as e:
        logger.exception(f"[Dist] User {user_id}: CRITICAL FAILURE in run_distance_calculation: {e}")
        await message_to_reply.reply_text(f"❌ Произошла внутренняя ошибка: {e}", parse_mode='HTML') 

    if context.user_data is not None:
        context.user_data.pop('is_distance_active', None) 
        context.user_data['just_finished_conversation'] = True 
        
    logger.info(f"[Dist] User {user_id}: Distance conversation ended.")
    return ConversationHandler.END

# --- Обработка отмены ---
async def cancel_distance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[Dist] User {user_id}: Cancelling distance conversation.")

    query = update.callback_query
    message = update.message
    
    message_to_reply: Optional[Message] = None
    if isinstance(message, Message):
        message_to_reply = message
    elif query and isinstance(query.message, Message):
        message_to_reply = query.message

    if query:
        await query.answer()
        await query.edit_message_text("Расчет расстояния отменён.")
    elif message_to_reply: 
        await message_to_reply.reply_text("Расчет расстояния отменён.", reply_markup=ReplyKeyboardRemove())

    if context.user_data is not None:
        context.user_data.pop('is_distance_active', None)
        context.user_data['just_finished_conversation'] = True
    logger.info(f"[Dist] User {user_id}: Distance conversation ended.")
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
        name="distance_conversation",
    )