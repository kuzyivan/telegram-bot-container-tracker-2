from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from db import SessionLocal
from models import TrackingSubscription
import datetime

# Состояния для ConversationHandler
TRACK_CONTAINERS, SET_TIME = range(2)

# 1. Запросить список контейнеров
async def ask_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Введите список контейнеров для слежения (через запятую):"
    )
    return TRACK_CONTAINERS

# 2. Получить список контейнеров от пользователя
async def receive_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    containers = [c.strip().upper() for c in update.message.text.split(',') if c.strip()]
    if not containers:
        await update.message.reply_text("Список контейнеров пуст. Повторите ввод:")
        return TRACK_CONTAINERS

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

# 3. Установить время рассылки и сохранить подписку в БД
async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_choice = update.callback_query.data.split("_")[1]
    time_obj = datetime.time(hour=9) if time_choice == "09" else datetime.time(hour=16)

    containers = context.user_data.get('containers', [])
    user_id = update.effective_user.id
    username = update.effective_user.username

    # Сохраняем подписку
    with SessionLocal() as session:
        sub = TrackingSubscription(
            user_id=user_id,
            username=username,
            containers=containers,  # ARRAY в Postgres
            notify_time=time_obj
        )
        session.add(sub)
        session.commit()

    await update.callback_query.message.reply_text(
        f"✅ Контейнеры {', '.join(containers)} поставлены на слежение в {time_obj.strftime('%H:%M')} (по местному времени)"
    )
    return ConversationHandler.END

# 4. Обработка отмены
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отмена слежения")
    return ConversationHandler.END

# ConversationHandler для главного меню
def tracking_conversation_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_containers, pattern="^track_request$")],
        states={
            TRACK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_containers)],
            SET_TIME: [CallbackQueryHandler(set_tracking_time, pattern="^time_")]
        },
        fallbacks=[MessageHandler(filters.COMMAND, cancel)],
    )
