# handlers/distance_handlers.py
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from services.tariff_service import get_tariff_distance
from logger import get_logger

logger = get_logger(__name__)

# --- Состояния диалога ---
ASK_FROM_STATION, ASK_TO_STATION = range(2)

# --- Вспомогательные функции для очистки (для отладки) ---
def _clean_station_name_for_input(raw_name: str) -> str:
    """Оставляет только имя станции без кода для поиска в справочнике."""
    import re
    # Удаляем код станции в скобках, чтобы найти чистое имя в 2-РП.csv
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', raw_name).strip()
    return cleaned if cleaned else raw_name.strip()

# --- Точка входа /distance ---
async def distance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог расчета расстояния."""
    if not update.message:
        return ConversationHandler.END

    await update.message.reply_text(
        "Пожалуйста, введите **станцию отправления** (можно без кода, например, 'ЧЕМСКОЙ')."
        "\nИли введите /cancel для отмены.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    context.user_data.clear() # Очищаем данные от предыдущих диалогов
    return ASK_FROM_STATION

# --- Обработка станции отправления ---
async def process_from_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию отправления и запрашивает станцию назначения."""
    if not update.message or not update.message.text:
        return ASK_FROM_STATION

    from_station_raw = update.message.text.strip()
    
    # Сохраняем RAW-имя. Ядро расчета само найдет код по названию.
    context.user_data['from_station_name'] = from_station_raw
    
    await update.message.reply_text(
        f"Станция отправления: **{from_station_raw}**.\n"
        "Теперь введите **станцию назначения**.",
        parse_mode='Markdown'
    )
    return ASK_TO_STATION

# --- Обработка станции назначения и выполнение расчета ---
async def process_to_station(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию назначения и выполняет расчет."""
    if not update.message or not update.message.text or 'from_station_name' not in context.user_data:
        # Если нет from_station_name, значит, диалог начат некорректно
        return ConversationHandler.END

    to_station_raw = update.message.text.strip()
    from_station_raw = context.user_data['from_station_name']
    
    await update.message.reply_text("⏳ Выполняю расчет тарифного расстояния...")

    # --- ⬇️ НАЧАЛО БЛОКА ИЗМЕНЕНИЙ (ВАРИАНТ 1: HTML) ⬇️ ---
    try:
        # 1. Используем get_tariff_distance, который теперь возвращает dict
        result = await get_tariff_distance(
            from_station_name=from_station_raw,
            to_station_name=to_station_raw
        )

        if result:
            # 2. Извлекаем данные
            distance = result['distance']
            info_a = result['info_a']
            info_b = result['info_b']

            # 3. ФОРМИРУЕМ НОВЫЙ HTML-ОТВЕТ
            response = (
                f"✅ <b>Расчет успешно выполнен!</b>\n\n"
                f"🚉 <b>Отправление:</b>\n"
                # Используем html.escape для безопасности, если имена содержат < или >
                # Но для названий станций это обычно не нужно, оставляем для чистоты
                f"<b>{info_a['station_name']}</b> <i>({info_a.get('railway', 'Н/Д')})</i>\n\n"
                f"🏁 <b>Назначение:</b>\n"
                f"<b>{info_b['station_name']}</b> <i>({info_b.get('railway', 'Н/Д')})</i>\n\n"
                f"————————————————\n"
                f"🛤️ <b>Тарифное расстояние: {distance} км</b>"
            )
            
            logger.info(f"[/distance] Успешный расчет: {info_a['station_name']} -> {info_b['station_name']} = {distance} км.")
            
            # 4. ❗️ Отправляем с parse_mode='HTML'
            await update.message.reply_text(response, parse_mode='HTML')

        else:
            # Блок 'else' (ошибка)
            from_cleaned = _clean_station_name_for_input(from_station_raw)
            to_cleaned = _clean_station_name_for_input(to_station_raw)
            
            response = (
                f"❌ <b>Не удалось найти маршрут.</b>\n\n"
                f"Проверьте названия станций в справочнике 2-РП.csv.\n"
                f"Поиск велся по очищенным именам:\n"
                f"Отпр: <code>{from_cleaned}</code>\n"
                f"Назн: <code>{to_cleaned}</code>"
            )
            logger.warning(f"[/distance] Расчет не удался для {from_station_raw} -> {to_station_raw}.")
            # ❗️ Отправляем с parse_mode='HTML'
            await update.message.reply_text(response, parse_mode='HTML')

    except Exception as e:
        logger.exception(f"Критическая ошибка в /distance: {e}")
        response = f"❌ Произошла внутренняя ошибка при расчете. Попробуйте позже."
        # ❗️ Отправляем с parse_mode='HTML'
        await update.message.reply_text(response, parse_mode='HTML')
    # --- ⬆️ КОНЕЦ БЛОКА ИЗМЕНЕНИЙ ⬆️ ---

    context.user_data.clear()
    return ConversationHandler.END

# --- Обработка отмены ---
async def cancel_distance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог."""
    if update.message:
        await update.message.reply_text("Расчет расстояния отменён.", reply_markup=ReplyKeyboardRemove())
    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

# --- Регистрация хендлеров ---
def distance_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("distance", distance_cmd)],
        states={
            ASK_FROM_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_from_station)],
            ASK_TO_STATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_to_station)],
        },
        fallbacks=[CommandHandler("cancel", cancel_distance)],
        allow_reentry=True,
    )