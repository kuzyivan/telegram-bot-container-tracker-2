from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
import datetime
from sqlalchemy import select
from db import SessionLocal, get_user_by_telegram_id
from models import TrackingSubscription
from utils.keyboards import cancel_tracking_confirm_keyboard, delivery_channel_keyboard
from logger import get_logger

logger = get_logger(__name__)

# Состояния для ConversationHandler
TRACK_CONTAINERS, SET_TIME, SET_CHANNEL = range(3)

# 1. Запросить список контейнеров
async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"[ask_containers] Пользователь {user_id} начал постановку на слежение.")

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Введите список контейнеров для слежения (через запятую):"
        )
    elif update.message:
        await update.message.reply_text("Введите список контейнеров для слежения (через запятую):")
    else:
        logger.warning("[ask_containers] Не удалось отправить сообщение пользователю.")

    return TRACK_CONTAINERS

# 2. Получить список контейнеров
async def receive_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        await update.message.reply_text("Пожалуйста, введите список контейнеров через запятую.")
        return TRACK_CONTAINERS

    containers = [c.strip().upper() for c in update.message.text.split(',') if c.strip()]
    if not containers:
        await update.message.reply_text("Список контейнеров пуст. Повторите ввод:")
        return TRACK_CONTAINERS

    context.user_data['containers'] = containers

    keyboard = [
        [InlineKeyboardButton("09:00", callback_data="time_09")],
        [InlineKeyboardButton("16:00", callback_data="time_16")]
    ]
    await update.message.reply_text("Выберите время отправки уведомлений:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_TIME

# 3. Установка времени уведомлений
async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.callback_query.data:
        return ConversationHandler.END

    await update.callback_query.answer()
    time_choice = update.callback_query.data.split("_")[1]
    notify_time = datetime.time(hour=int(time_choice))
    context.user_data['notify_time'] = notify_time

    await update.callback_query.message.reply_text(
        "Куда присылать уведомления по этой подписке?",
        reply_markup=delivery_channel_keyboard()
    )
    return SET_CHANNEL

# 4. Выбор канала доставки и финальное сохранение
async def set_delivery_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.callback_query.data:
        return ConversationHandler.END

    await update.callback_query.answer()
    delivery_channel = update.callback_query.data.replace("delivery_channel_", "")
    user = update.effective_user

    containers = context.user_data.get('containers')
    notify_time = context.user_data.get('notify_time')
    user_obj = await get_user_by_telegram_id(user.id)

    if delivery_channel in ["email", "both"] and (not user_obj or not user_obj.email):
        await update.callback_query.message.reply_text("У тебя не указан e-mail. Введи /set_email и начни заново.")
        return ConversationHandler.END

    try:
        async with SessionLocal() as session:
            subscription = TrackingSubscription(
                user_id=user.id,
                username=user.username,
                containers=containers,
                notify_time=notify_time,
                delivery_channel=delivery_channel
            )
            session.add(subscription)
            await session.commit()

        await update.callback_query.message.reply_text(
            f"✅ Контейнеры {', '.join(containers)} поставлены на слежение в {notify_time.strftime('%H:%M')} через: {delivery_channel}"
        )
        logger.info(f"[set_delivery_channel] Подписка сохранена для {user.id}: {containers}")
    except Exception as e:
        logger.error(f"[set_delivery_channel] Ошибка: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ Не удалось сохранить подписку. Попробуйте позже.")

    return ConversationHandler.END

# /canceltracking — подтверждение отмены
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"[cancel] Пользователь {user_id} вызвал /canceltracking")
    await update.message.reply_text(
        "⚠️ Ты уверен, что хочешь отменить все активные слежения?",
        reply_markup=cancel_tracking_confirm_keyboard()
    )

# Подтверждение удаления подписок
async def cancel_tracking_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.callback_query.answer()

    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(TrackingSubscription).where(TrackingSubscription.user_id == user_id)
            )
            subs = result.scalars().all()
            if not subs:
                await update.callback_query.edit_message_text("У тебя нет активных подписок.")
                return

            for sub in subs:
                await session.delete(sub)
            await session.commit()

        await update.callback_query.edit_message_text("✅ Все подписки удалены.")
        logger.info(f"[cancel_tracking_confirm] Подписки удалены для {user_id}")
    except Exception as e:
        logger.error(f"[cancel_tracking_confirm] Ошибка удаления подписок: {e}", exc_info=True)
        await update.callback_query.edit_message_text("❌ Ошибка при удалении подписок. Попробуй позже.")

# ConversationHandler

def tracking_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_containers, pattern="^track_request$"),
            MessageHandler(filters.Regex("^🔔 Задать слежение$"), ask_containers)
        ],
        states={
            TRACK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_containers)],
            SET_TIME: [CallbackQueryHandler(set_tracking_time, pattern="^time_")],
            SET_CHANNEL: [CallbackQueryHandler(set_delivery_channel, pattern="^delivery_channel_")]
        },
        fallbacks=[],
    )