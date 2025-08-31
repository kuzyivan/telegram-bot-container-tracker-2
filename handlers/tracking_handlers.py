# handlers/tracking_handlers.py
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, CommandHandler
)
from db import SessionLocal
from sqlalchemy import delete
from models import TrackingSubscription
import datetime
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

# Определяем состояния для диалога
TRACK_CONTAINERS, SET_TIME = range(2)

async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог по установке слежения, запрашивая номера контейнеров."""
    user = update.effective_user
    logger.info(f"Пользователь {getattr(user, 'id', 'Unknown')} начал постановку на слежение.")
    if context.user_data is None:
        context.user_data = {}

    text = "Введите номера контейнеров для слежения (можно через пробел, запятую или с новой строки):"

    # Запоминаем ID сообщений для последующей очистки чата
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
    message = update.message
    if not message:
        return TRACK_CONTAINERS
    
    if not message.text:
        await message.reply_text("Пожалуйста, отправьте текстовое сообщение с номерами контейнеров.")
        return TRACK_CONTAINERS

    # Разделяем по любому пробельному символу (пробел, перенос строки) или запятой
    containers = [c.strip().upper() for c in re.split(r'[\s,]+', message.text) if c.strip()]
    
    if not containers:
        await message.reply_text("Список контейнеров пуст. Пожалуйста, повторите ввод или нажмите /cancel для отмены.")
        return TRACK_CONTAINERS

    if context.user_data is None:
        context.user_data = {}
    context.user_data['containers'] = containers
    context.user_data['container_message_id'] = message.message_id

    keyboard = [
        [InlineKeyboardButton("09:00", callback_data="time_09")],
        [InlineKeyboardButton("16:00", callback_data="time_16")]
    ]
    await message.reply_text(
        "Отлично! Теперь выберите время отправки ежедневных отчетов:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SET_TIME

async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет подписку в БД и удаляет сообщения диалога для чистоты чата."""
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

    user_id_for_logs = user.id

    try:
        logger.info(f"Пользователь {user.id} ({user.username}) устанавливает слежение на контейнеры {containers} в {time_obj.strftime('%H:%M')}")
        
        async with SessionLocal() as session:
            await session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == user.id))
            
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
        logger.error(f"Ошибка при сохранении подписки пользователя {user_id_for_logs}: {e}", exc_info=True)
        if query.message:
            await query.edit_message_text("❌ Не удалось сохранить подписку. Попробуйте позже.")
            
    finally:
        if context.user_data:
            context.user_data.clear()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отмену внутри диалога установки слежения."""
    if update.message:
        await update.message.reply_text("❌ Установка слежения отменена.")
    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

async def cancel_tracking_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог отмены всех слежений."""
    text = "Вы уверены, что хотите отменить все ваши слежения?"
    keyboard = cancel_tracking_confirm_keyboard

    if update.callback_query:
        await update.callback_query.answer()
        if update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, text, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard)

async def cancel_tracking_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает или отменяет удаление всех подписок пользователя."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if query.data == "cancel_tracking_no":
        await query.edit_message_text("Действие отменено.")
        return

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

async def cancel_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /canceltracking для быстрой отмены."""
    if not update.message or not update.message.from_user:
        return
    
    user_id = update.message.from_user.id
    try:
        async with SessionLocal() as session:
            await session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id))
            await session.commit()
        await update.message.reply_text("✅ Все ваши слежения успешно отменены.")
        logger.info(f"Все слежения пользователя {user_id} удалены по команде /canceltracking.")
    except Exception as e:
        logger.error(f"Ошибка при удалении слежений пользователя {user_id} по команде: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Ошибка при отмене слежений.")

def tracking_conversation_handler():
    """Собирает все обработчики, связанные с установкой слежения, в один ConversationHandler."""
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

    parts: list[str] = [f"📦 <b>Контейнер</b>: <code>{container_number}</code>"]
    if train:
        parts.append(f"🚂 <b>Поезд</b>: <code>{train}</code>")
    
    parts.extend([
        "\n🛤 <b>Маршрут</b>:", f"<b>{route_from}</b> 🚂 → <b>{route_to}</b>",
        f"\n📍 <b>Текущая станция</b>: {station_now}", "📅 <b>Последняя операция</b>:", last_operation_text,
        f"\n🚆 <b>Вагон</b>: <code>{wagon_text}</code>", f"📏 <b>Осталось ехать</b>: <b>{_fmt_num(distance_km)}</b> км",
        "\n⏳ <b>Оценка времени в пути</b>:", f"~<b>{_fmt_num(eta_days)}</b> суток"
    ])
    text = "\n".join(parts)

    try:
        if update.message:
            await update.message.reply_html(text)
        elif update.callback_query and isinstance(update.callback_query.message, Message):
            await update.callback_query.message.reply_html(text)
        elif update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка отправки ответа о дислокации: {e}", exc_info=True)