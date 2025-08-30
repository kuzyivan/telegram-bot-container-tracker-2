# handlers/tracking_handlers.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, CommandHandler
)
from db import SessionLocal
from sqlalchemy import delete
from models import TrackingSubscription
import datetime
# ВАЖНО: убедитесь, что utils.keyboards импортирует обновленную Inline-клавиатуру
from utils.keyboards import cancel_tracking_confirm_keyboard
from logger import get_logger
from queries.containers import get_latest_train_by_container

logger = get_logger(__name__)

def _fmt_num(x):
    """Форматирование чисел: убирает .0."""
    try:
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x)
    except (ValueError, TypeError):
        return str(x)

TRACK_CONTAINERS, SET_TIME = range(2)

async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог по установке слежения, запрашивая номера контейнеров."""
    user = update.effective_user
    logger.info(f"Пользователь {getattr(user, 'id', 'Unknown')} начал постановку на слежение.")
    if context.user_data is None:
        context.user_data = {}

    text = "Введите список контейнеров для слежения (через запятую или пробел):"
    
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.message:
            context.user_data['start_message_id'] = update.callback_query.message.message_id
        if update.effective_chat:
            sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            context.user_data['prompt_message_id'] = sent_message.message_id
    elif update.message:
        context.user_data['start_message_id'] = update.message.message_id
        sent_message = await update.message.reply_text(text)
        context.user_data['prompt_message_id'] = sent_message.message_id
        
    return TRACK_CONTAINERS

async def receive_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает номера контейнеров, сохраняет их и запрашивает время."""
    if not update.message or not update.message.text:
        return TRACK_CONTAINERS

    containers = [c.strip().upper() for c in update.message.text.split(',') if c.strip()]
    if not containers:
        await update.message.reply_text("Список контейнеров пуст. Повторите ввод:")
        return TRACK_CONTAINERS

    if context.user_data is None:
        context.user_data = {}
    context.user_data['containers'] = containers
    context.user_data['container_message_id'] = update.message.message_id

    keyboard = [
        [InlineKeyboardButton("09:00", callback_data="time_09")],
        [InlineKeyboardButton("16:00", callback_data="time_16")]
    ]
    await update.message.reply_text(
        "Выберите время отправки уведомлений:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SET_TIME

async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет подписку в БД и удаляет ВСЕ сообщения диалога."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()
    time_choice = query.data.split("_")[1]
    time_obj = datetime.time(hour=9) if time_choice == "09" else datetime.time(hour=16)

    if context.user_data is None:
        logger.warning("user_data в контексте отсутствует, прерываю установку слежения.")
        return ConversationHandler.END
    containers = context.user_data.get('containers', [])
    
    user = update.effective_user
    if not user:
        logger.warning("Отсутствует effective_user в update, прерываю установку слежения.")
        return ConversationHandler.END

    logger.info(f"Пользователь {user.id} ({user.username}) ставит контейнеры {containers} на {time_obj.strftime('%H:%M')}")

    try:
        async with SessionLocal() as session:
            sub = TrackingSubscription(user_id=user.id, username=user.username, containers=containers, notify_time=time_obj)
            session.add(sub)
            await session.commit()
        logger.info(f"Подписка успешно сохранена для пользователя {user.id} на {time_obj.strftime('%H:%M')}")

        confirmation_text = f"✅ Слежение для: {', '.join(containers)} установлено на {time_obj.strftime('%H:%M')}"
        if query.message:
            await query.edit_message_text(text=confirmation_text)

        await asyncio.sleep(5)

        try:
            chat_id = update.effective_chat.id if update.effective_chat else None
            if not chat_id: return

            message_ids_to_delete = [
                context.user_data.get('start_message_id'),
                context.user_data.get('prompt_message_id'),
                context.user_data.get('container_message_id'),
                query.message.message_id if query.message else None,
            ]
            
            for msg_id in message_ids_to_delete:
                if msg_id:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
            
        except Exception as e:
            logger.warning(f"Не удалось полностью очистить чат после установки слежения: {e}")

    except Exception as e:
        logger.error(f"Ошибка при сохранении подписки пользователя {user.id}: {e}", exc_info=True)
        if query.message:
            await query.edit_message_text("❌ Не удалось сохранить подписку. Попробуйте позже.")
            
    finally:
        if context.user_data:
            context.user_data.clear()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отмену внутри диалога."""
    if update.message:
        await update.message.reply_text("❌ Установка слежения отменена.")
    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

async def cancel_tracking_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог отмены всех слежений."""
    text = "Вы уверены, что хотите отменить все ваши слежения?"
    # Эта клавиатура теперь должна быть типа InlineKeyboardMarkup
    keyboard = cancel_tracking_confirm_keyboard

    if update.callback_query:
        await update.callback_query.answer()
        if update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, text, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard)

# --- ИЗМЕНЁННАЯ ФУНКЦИЯ ---
async def cancel_tracking_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает или отменяет удаление всех подписок пользователя."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    # Если пользователь передумал
    if query.data == "cancel_tracking_no":
        await query.edit_message_text("Действие отменено.")
        return

    # Если пользователь подтвердил отмену
    if query.data == "cancel_tracking_yes":
        try:
            async with SessionLocal() as session:
                await session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == query.from_user.id))
                await session.commit()
            await query.edit_message_text("✅ Все ваши слежения успешно отменены.")
            logger.info(f"Все слежения пользователя {query.from_user.id} удалены.")
        except Exception as e:
            logger.error(f"Ошибка при отмене слежений пользователя {query.from_user.id}: {e}", exc_info=True)
            await query.edit_message_text("❌ Произошла ошибка при отмене слежений.")
# --- КОНЕЦ ИЗМЕНЕНИЙ ---

async def cancel_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /canceltracking."""
    if not update.message or not update.message.from_user:
        return
    
    user_id = update.message.from_user.id
    try:
        async with SessionLocal() as session:
            await session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id))
            await session.commit()
        await update.message.reply_text("❌ Все ваши слежения отменены.")
        logger.info(f"Все слежения пользователя {user_id} удалены.")
    except Exception as e:
        logger.error(f"Ошибка при удалении слежений пользователя {user_id}: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Ошибка при отмене слежений.")

def tracking_conversation_handler():
    """Собирает все обработчики слежения в один ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_containers, pattern="^track_request$"),
            MessageHandler(filters.Regex("^🔔 Задать слежение$"), ask_containers),
        ],
        states={
            TRACK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_containers)],
            SET_TIME: [CallbackQueryHandler(set_tracking_time, pattern="^time_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

async def send_container_dislocation_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    container_number: str, route_from: str, route_to: str, station_now: str,
    last_operation_text: str, wagon_text: str, distance_km: float | int,
    eta_days: float | int,
) -> None:
    """Формирует и отправляет карточку с информацией о дислокации контейнера."""
    try:
        train = await get_latest_train_by_container(container_number)
    except Exception as e:
        logger.error(f"Ошибка получения train для {container_number}: {e}", exc_info=True)
        train = None

    parts: list[str] = [f"📦 Контейнер: {container_number}"]
    if train:
        parts.append(f"🚂 Поезд: {train}")
    
    parts.extend([
        "\n🛤 Маршрут:", f"{route_from} 🚂 → {route_to}",
        f"\n📍 Текущая станция: {station_now}", "📅 Последняя операция:", last_operation_text,
        f"\n🚆 Вагон: {wagon_text}", f"📏 Осталось ехать: {_fmt_num(distance_km)} км",
        "\n⏳ Оценка времени в пути:", f"~{_fmt_num(eta_days)} суток"
    ])
    text = "\n".join(parts)

    if update.message:
        await update.message.reply_text(text)
    elif update.callback_query:
        message = update.callback_query.message
        if message and isinstance(message, Message):
            await message.reply_text(text)
    elif update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)