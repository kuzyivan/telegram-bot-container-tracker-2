from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
import db
from db import SessionLocal
from sqlalchemy import delete, select
from models import TrackingSubscription
import datetime
from utils.keyboards import cancel_tracking_confirm_keyboard, delivery_channel_keyboard
from logger import get_logger

logger = get_logger(__name__)

# Состояния для ConversationHandler
TRACK_CONTAINERS, SET_TIME, SET_CHANNEL = range(3)

# 1. Запросить список контейнеров
async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user is not None else "Unknown"
    logger.info(f"[ask_containers] Пользователь {user_id} начал постановку на слежение.")
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.message is not None:
            if update.effective_chat is not None:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Введите список контейнеров для слежения (через запятую):"
                )
            else:
                logger.warning("[ask_containers] effective_chat is None, cannot send message.")
        else:
            logger.warning("[ask_containers] callback_query.message is None, cannot send reply_text.")
    else:
        if update.message is not None:
            await update.message.reply_text(
                "Введите список контейнеров для слежения (через запятую):"
            )
        else:
            logger.warning("[ask_containers] update.message is None, cannot send reply_text.")
    return TRACK_CONTAINERS

# 2. Получить список контейнеров от пользователя
async def receive_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
        logger.warning(f"[receive_containers] Нет текста сообщения от пользователя {user_id}")
        if update.message is not None:
            await update.message.reply_text("Пожалуйста, введите список контейнеров через запятую.")
        return TRACK_CONTAINERS
    containers = [c.strip().upper() for c in update.message.text.split(',') if c.strip()]
    if not containers:
        user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
        logger.warning(f"[receive_containers] Пустой ввод контейнеров от пользователя {user_id}")
        await update.message.reply_text("Список контейнеров пуст. Повторите ввод:")
        return TRACK_CONTAINERS

    user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
    logger.info(f"[receive_containers] Пользователь {user_id} выбрал контейнеры: {containers}")
    if context.user_data is None:
        context.user_data = {}
    context.user_data['containers'] = containers

    keyboard = [
        [InlineKeyboardButton("09:00", callback_data="time_09")],
        [InlineKeyboardButton("16:00", callback_data="time_16")]
    ]
    await update.message.reply_text(
        "Выберите время отправки уведомлений:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SET_TIME

# 3. Получить время и спросить канал доставки
async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("== [set_tracking_time] Показываю выбор канала доставки пользователю ==")

    if update.callback_query is not None and update.callback_query.data is not None:
        await update.callback_query.answer()
        time_choice = update.callback_query.data.split("_")[1]
    else:
        logger.warning("[set_tracking_time] update.callback_query is None или data is None.")
        return ConversationHandler.END

    time_obj = datetime.time(hour=9) if time_choice == "09" else datetime.time(hour=16)

    if context.user_data is None:
        context.user_data = {}
    context.user_data['notify_time'] = time_obj

    # Предлагаем выбрать канал доставки
    await update.callback_query.message.reply_text(
        "Куда присылать уведомления по этой подписке?",
        reply_markup=delivery_channel_keyboard()
    )
    return SET_CHANNEL

# 4. Получить канал доставки, проверить e-mail, создать подписку
async def set_delivery_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is None or update.callback_query.data is None:
        logger.warning("[set_delivery_channel] update.callback_query is None или data is None.")
        return ConversationHandler.END
    await update.callback_query.answer()
    channel = update.callback_query.data.replace("delivery_channel_", "")
    user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
    username = update.effective_user.username if update.effective_user is not None else "Unknown"

    # Получаем пользователя из базы
    user = await db.get_user_by_telegram_id(user_id)
    if channel in ["email", "both"]:
        if not user or not user.email:
            await update.callback_query.message.reply_text(
                "У тебя не указан e-mail. Введи команду /set_email и оформи подписку заново."
            )
            return ConversationHandler.END

    if context.user_data is None:
        logger.error("[set_delivery_channel] context.user_data is None, ничего не сохранилось, отмена.")
        await update.callback_query.message.reply_text("Ошибка: не удалось сохранить данные подписки.")
        return ConversationHandler.END

    containers = context.user_data.get('containers', [])
    notify_time = context.user_data.get('notify_time', None)

    try:
        async with SessionLocal() as session:
            sub = TrackingSubscription(
                user_id=user_id,
                username=username,
                containers=containers,
                notify_time=notify_time,
                delivery_channel=channel
            )
            session.add(sub)
            await session.commit()
        logger.info(f"[set_delivery_channel] Подписка успешно сохранена для пользователя {user_id}: {containers}, {notify_time}, канал: {channel}")
        await update.callback_query.message.reply_text(
            f"✅ Контейнеры {', '.join(containers)} поставлены на слежение в {notify_time.strftime('%H:%M')} по каналу: {channel}"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"[set_delivery_channel] Ошибка при сохранении подписки пользователя {user_id}: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ Не удалось сохранить подписку. Попробуйте позже.")
        return ConversationHandler.END

# ConversationHandler для главного меню с обновлёнными состояниями
def tracking_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_containers, pattern="^track_request$"),
            MessageHandler(filters.Regex("^🔔 Задать слежение$"), ask_containers),
        ],
        states={
            TRACK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_containers)],
            SET_TIME: [CallbackQueryHandler(set_tracking_time, pattern="^time_")],
            SET_CHANNEL: [CallbackQueryHandler(set_delivery_channel, pattern="^delivery_channel_")]
        },
        fallbacks=[],
    )