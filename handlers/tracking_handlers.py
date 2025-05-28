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

async def stop_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with SessionLocal() as session:
        deleted = session.query(TrackingSubscription).filter_by(user_id=user_id).delete()
        session.commit()
    if deleted:
        await update.message.reply_text("✅ Все ваши подписки на слежение удалены.")
    else:
        await update.message.reply_text("У вас нет активных подписок на слежение.")

async def send_tracking_notifications(context, notify_time: str):
    from telegram import Bot
    from models import TrackingSubscription
    from db import SessionLocal

    hour, minute = map(int, notify_time.split(":"))
    with SessionLocal() as session:
        subs = session.query(TrackingSubscription).filter(
            TrackingSubscription.notify_time == datetime.time(hour=hour, minute=minute)
        ).all()
    for sub in subs:
        msg = f"⏰ Напоминание о контейнерах: {', '.join(sub.containers)}"
        try:
            await context.bot.send_message(chat_id=sub.user_id, text=msg)
        except Exception as e:
            print(f"Ошибка отправки пользователю {sub.user_id}: {e}")

async def testnotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_tracking_notifications(context, '16:00')
    await update.message.reply_text("Тестовая рассылка выполнена.")
