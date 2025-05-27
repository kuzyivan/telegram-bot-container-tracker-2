from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

TRACK_CONTAINERS, SET_TIME = range(2)
user_tracking_data = {}

async def ask_containers(update: Update, context: CallbackContext.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Введите список контейнеров для слежения (через запятую):")
    return TRACK_CONTAINERS

async def receive_containers(update: Update, context: CallbackContext.DEFAULT_TYPE):
    containers = [c.strip().upper() for c in update.message.text.split(',')]
    context.user_data['containers'] = containers

    keyboard = [
        [InlineKeyboardButton("09:00", callback_data="time_09")],
        [InlineKeyboardButton("16:00", callback_data="time_16")]
    ]
    await update.message.reply_text("Выберите время отправки уведомлений:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_TIME

async def set_tracking_time(update: Update, context: CallbackContext.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_choice = update.callback_query.data.split("_")[1]
    context.user_data['time'] = "09:00" if time_choice == "09" else "16:00"

    # Здесь добавь сохранение в БД или планировщик
    containers = context.user_data['containers']
    time_str = context.user_data['time']
    await update.callback_query.message.reply_text(
        f"✅ Контейнеры {', '.join(containers)} поставлены на слежение в {time_str} (по местному времени)"
    )

    # Очистка если нужно
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отмена слежения")
    return ConversationHandler.END

def tracking_conversation_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_containers, pattern="^track_request$")],
        states={
            TRACK_CONTAINERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_containers)],
            SET_TIME: [CallbackQueryHandler(set_tracking_time, pattern="^time_")]
        },
        fallbacks=[MessageHandler(filters.COMMAND, cancel)],
    )
