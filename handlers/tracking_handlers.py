from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from db import SessionLocal
from sqlalchemy import delete
from models import TrackingSubscription
import datetime
from utils.keyboards import cancel_tracking_confirm_keyboard
from logger import get_logger

logger = get_logger(__name__)

# Состояния для ConversationHandler
TRACK_CONTAINERS, SET_TIME = range(2)

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

# 3. Установить время рассылки и сохранить подписку в БД
async def set_tracking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None and update.callback_query.data is not None:
        await update.callback_query.answer()
        time_choice = update.callback_query.data.split("_")[1]
    else:
        logger.warning("[set_tracking_time] update.callback_query is None or data is None, cannot answer or get data.")
        return ConversationHandler.END
    time_obj = datetime.time(hour=9) if time_choice == "09" else datetime.time(hour=16)

    if context.user_data is None:
        context.user_data = {}
    containers = context.user_data.get('containers', [])
    user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
    username = update.effective_user.username if update.effective_user is not None else "Unknown"

    logger.info(f"[set_tracking_time] Пользователь {user_id} ({username}) ставит контейнеры {containers} на {time_obj.strftime('%H:%M')}")

    try:
        session = SessionLocal()
        try:
            sub = TrackingSubscription(
                user_id=user_id,
                username=username,
                containers=containers,  # ARRAY в Postgres
                notify_time=time_obj
            )
            session.add(sub)
            session.commit()
        finally:
            session.close()
        logger.info(f"[set_tracking_time] Подписка успешно сохранена для пользователя {user_id} на {time_obj.strftime('%H:%M')}")
        if update.effective_chat is not None:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Контейнеры {', '.join(containers)} поставлены на слежение в {time_obj.strftime('%H:%M')} (по местному времени)"
            )
        else:
            logger.warning("[set_tracking_time] effective_chat is None, cannot send confirmation message.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"[set_tracking_time] Ошибка при сохранении подписки пользователя {user_id}: {e}", exc_info=True)
        await update.callback_query.edit_message_text("❌ Не удалось сохранить подписку. Попробуйте позже.")
        return ConversationHandler.END

# 4. Обработка отмены внутри ConversationHandler
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user is not None else "Unknown"
    logger.info(f"[cancel] Отмена слежения для пользователя {user_id}")
    if update.message is not None:
        await update.message.reply_text("❌ Отмена слежения")
    else:
        logger.warning("[cancel] update.message is None, cannot send reply_text.")
    return ConversationHandler.END

# 5. Старт отмены слежения (кнопка)
async def cancel_tracking_start(update, context):
    logger.info(f"[cancel_tracking_start] Запрошена отмена слежения пользователем {update.effective_user.id}")
    await update.message.reply_text(
        "Вы уверены, что хотите отменить все ваши слежения?",
        reply_markup=cancel_tracking_confirm_keyboard
    )

# 6. Callback обработка подтверждения/отмены
async def cancel_tracking_confirm(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "cancel_tracking_yes":
        try:
            session = SessionLocal()
            try:
                session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id))
                session.commit()
            finally:
                session.close()
            await query.edit_message_text("❌ Все ваши слежения отменены.")
            logger.info(f"[cancel_tracking_confirm] Все слежения пользователя {user_id} удалены.")
        except Exception as e:
            logger.error(f"[cancel_tracking_confirm] Ошибка при отмене слежений пользователя {user_id}: {e}", exc_info=True)
            await query.edit_message_text("❌ Ошибка при отмене слежений.")
    elif query.data == "cancel_tracking_no":
        logger.info(f"[cancel_tracking_confirm] Пользователь {user_id} отменил отмену слежений.")
        await query.edit_message_text("Отмена слежения не выполнена.")

# Старый вариант для команды /canceltracking
    try:
        session = SessionLocal()
        try:
            session.execute(delete(TrackingSubscription).where(TrackingSubscription.user_id == user_id))
            session.commit()
        finally:
            session.close()
        await update.message.reply_text("❌ Все ваши слежения отменены.")
        logger.info(f"[cancel_tracking] Все слежения пользователя {user_id} удалены.")
    except Exception as e:
        logger.error(f"[cancel_tracking] Ошибка при удалении слежений пользователя {user_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при отмене слежений.")

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