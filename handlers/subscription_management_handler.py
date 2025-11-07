# handlers/subscription_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# --- 🐞 НОВЫЙ ИМПОРТ 🐞 ---
from telegram.error import BadRequest
# --- 🏁 КОНЕЦ ИМПОРТА 🏁 ---
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler,
    ConversationHandler, MessageHandler, filters 
)
from queries.subscription_queries import ( 
    get_user_subscriptions, delete_subscription, get_subscription_details,
    add_container_to_subscription, remove_container_from_subscription 
)
from queries.user_queries import register_user_if_not_exists 
from logger import get_logger

# Импорт парсера контейнеров из tracking_handlers
try:
    from .tracking_handlers import normalize_containers
except ImportError:
    # Запасной вариант, если структура другая
    from handlers.tracking_handlers import normalize_containers

from utils.keyboards import create_yes_no_inline_keyboard

logger = get_logger(__name__)

# --- ОБНОВЛЕННЫЕ СОСТОЯНИЯ ---
(ASK_ADD_CONTAINERS, AWAIT_REMOVE_INPUT) = range(10, 12) # Добавлено состояние для удаления
# ---

async def my_subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message and not update.callback_query or not update.effective_user: # Учитываем CallbackQuery
        return
    
    await register_user_if_not_exists(update.effective_user) 
    
    subs = await get_user_subscriptions(update.effective_user.id)
    keyboard = []
    text = "📂 *Ваши подписки*\n\n"
    if not subs:
        text += "У вас пока нет активных подписок."
    else:
        text += "Выберите подписку для управления:"
        for sub in subs:
            keyboard.append([InlineKeyboardButton(f"{sub.subscription_name} ({sub.id})", callback_data=f"sub_menu_{sub.id}")]) 
    keyboard.append([InlineKeyboardButton("➕ Создать новую подписку", callback_data="create_sub_start")])
    
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        logger.warning("Не удалось получить chat_id в my_subscriptions_command")
        return

    await context.bot.send_message(
        chat_id=chat_id, 
        text=text, 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )


async def subscription_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    
    subscription_id_str = query.data.split("_")[-1]
    
    if not subscription_id_str.isdigit():
        logger.warning(f"subscription_menu_callback не смог определить ID подписки из data: {query.data}")
        await query.edit_message_text("❌ Ошибка: не удалось определить ID подписки.")
        return
        
    subscription_id = int(subscription_id_str)
    
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.edit_message_text("❌ Ошибка: подписка не найдена или не принадлежит вам.")
        return
        
    email_list = [sub_email.email.email for sub_email in sub.target_emails]
    
    emails_text = '`' + '`, `'.join(email_list) + '`' if email_list else 'Только в Telegram'
    status_text = 'Активна ✅' if sub.is_active is True else 'Неактивна ⏸️'
    containers_count = len(sub.containers) if sub.containers is not None else 0
    text = (
        f"⚙️ *Управление подпиской:*\n"
        f"*{sub.subscription_name}* `({sub.id})`\n\n"
        f"Статус: {status_text}\n"
        f"Время отчета: {sub.notification_time.strftime('%H:%M')}\n" 
        f"Контейнеров: {containers_count} шт.\n"
        f"Email для отчетов: {emails_text}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 Показать контейнеры", callback_data=f"sub_show_{sub.id}")],
        [
            InlineKeyboardButton("➕ Добавить контейнеры", callback_data=f"sub_add_ctn_{sub.id}"),
            InlineKeyboardButton("➖ Удалить контейнеры", callback_data=f"sub_rem_ctn_{sub.id}")
        ],
        [InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"sub_delete_{sub.id}")],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data="sub_back_to_list")]
    ]
    
    # --- 🐞 НАЧАЛО ИСПРАВЛЕНИЯ (Message not modified) 🐞 ---
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Меню подписки не изменилось, пропуск редактирования.")
        else:
            logger.error(f"Ошибка в subscription_menu_callback: {e}", exc_info=True)
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---


async def show_containers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.answer("❌ Ошибка: подписка не найдена.", show_alert=True)
        return
    if not sub.containers or len(sub.containers) == 0:
        text = "В этой подписке нет контейнеров."
    else:
        container_list = "\n".join(f"`{c}`" for c in sub.containers)
        text = f"Контейнеры в подписке *{sub.subscription_name}*:\n{container_list}"
    
    if update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def delete_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
    
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.edit_message_text("❌ Ошибка: подписка не найдена.")
        return
    
    text = f"Вы уверены, что хотите удалить подписку *{sub.subscription_name}*?"
    
    reply_markup = create_yes_no_inline_keyboard(
        yes_callback_data=f"sub_delete_confirm_yes_{sub.id}",
        no_callback_data=f"sub_menu_{sub.id}"
    )
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def delete_subscription_confirm_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    
    subscription_id = int(query.data.split("_")[-1])
    
    deleted = await delete_subscription(subscription_id, query.from_user.id)
    
    if deleted:
        await query.edit_message_text("✅ Подписка успешно удалена.")
    else:
        await query.edit_message_text("❌ Не удалось удалить подписку.")


async def back_to_subscriptions_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    subs = await get_user_subscriptions(query.from_user.id)
    keyboard = []
    text = "📂 *Ваши подписки*\n\n"
    if not subs:
        text += "У вас пока нет активных подписок."
    else:
        text += "Выберите подписку для управления:"
        for sub in subs:
            keyboard.append([InlineKeyboardButton(f"{sub.subscription_name} ({sub.id})", callback_data=f"sub_menu_{sub.id}")])
    keyboard.append([InlineKeyboardButton("➕ Создать новую подписку", callback_data="create_sub_start")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


# --- CONVERSATION HANDLER ДЛЯ УДАЛЕНИЯ КОНТЕЙНЕРОВ ---

async def remove_containers_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показывает меню для удаления (кнопки + текст) и входит в состояние AWAIT_REMOVE_INPUT.
    """
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        if query: await query.answer()
        return ConversationHandler.END
        
    if context.user_data:
        context.user_data.clear()

    subscription_id = int(query.data.split("_")[-1])
    user_id = query.from_user.id
    
    context.user_data['sub_id_to_edit'] = subscription_id
    
    sub = await get_subscription_details(subscription_id, user_id)
    
    if not sub:
        await query.answer("❌ Ошибка: подписка не найдена.", show_alert=True)
        return ConversationHandler.END
        
    await query.answer()
    keyboard = []
    text = (
        f"Выберите контейнеры для **поштучного** удаления из подписки *{sub.subscription_name}*:\n\n"
        "Или отправьте **список** контейнеров (через пробел/запятую) для удаления.\n\n"
        "Для отмены введите /cancel."
    )
    
    if sub.containers:
        for container in sub.containers:
            # callback_data: sub_rem_do_{id подписки}_{номер контейнера}
            keyboard.append([
                InlineKeyboardButton(f"🗑️ {container}", callback_data=f"sub_rem_do_{sub.id}_{container}")
            ])
    else:
        text = "В этой подписке уже нет контейнеров.\n\nДля отмены введите /cancel."
        
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_rem_back_{sub.id}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return AWAIT_REMOVE_INPUT

async def remove_container_do_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    (ВНУТРИ ДИАЛОГА) Обрабатывает нажатие на кнопку с контейнером для удаления.
    """
    query = update.callback_query
    if not query or not query.data or not query.from_user or not context.user_data:
        return ConversationHandler.END
        
    parts = query.data.split("_")
    if len(parts) < 5: 
        logger.warning(f"Ошибка парсинга callback_data в remove_container_do_conversation: {query.data}")
        await query.answer("❌ Ошибка данных.", show_alert=True)
        return AWAIT_REMOVE_INPUT # Остаемся в том же состоянии
        
    try:
        subscription_id = int(parts[3])
        container_number = "_".join(parts[4:])
        user_id = query.from_user.id
        
        if subscription_id != context.user_data.get('sub_id_to_edit'):
             await query.answer("❌ Ошибка сессии.", show_alert=True)
             return ConversationHandler.END
            
        success = await remove_container_from_subscription(subscription_id, container_number, user_id)
        
        if not success:
            await query.answer(f"❌ Не удалось удалить {container_number}.", show_alert=True)
            return AWAIT_REMOVE_INPUT
            
        await query.answer(f"✅ {container_number} удален.")
        
        sub = await get_subscription_details(subscription_id, user_id)
        if not sub:
            await query.edit_message_text("❌ Ошибка: подписка не найдена.")
            return ConversationHandler.END

        keyboard = []
        text = (
            f"Выберите контейнеры для **поштучного** удаления из подписки *{sub.subscription_name}*:\n\n"
            "Или отправьте **список** контейнеров (через пробел/запятую) для удаления.\n\n"
            "Для отмены введите /cancel."
        )
        
        if sub.containers:
            for container in sub.containers:
                keyboard.append([
                    InlineKeyboardButton(f"🗑️ {container}", callback_data=f"sub_rem_do_{sub.id}_{container}")
                ])
        else:
            text = "Все контейнеры удалены.\n\nДля отмены введите /cancel."
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_rem_back_{sub.id}")])

        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception as e:
            logger.info(f"Ошибка редактирования сообщения (возможно, не изменилось): {e}")
            pass
        
        return AWAIT_REMOVE_INPUT # Остаемся в том же состоянии
            
    except Exception as e:
        logger.error(f"Ошибка в remove_container_do_conversation: {e}", exc_info=True)
        await query.answer("❌ Произошла внутренняя ошибка.", show_alert=True)
        return AWAIT_REMOVE_INPUT

async def remove_containers_by_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    (ВНУТРИ ДИАЛОГА) Обрабатывает текстовое сообщение со списком контейнеров на удаление.
    """
    if (
        not update.message or not update.message.text or
        not context.user_data or not update.effective_user
    ):
        return ConversationHandler.END
        
    subscription_id = context.user_data.get('sub_id_to_edit')
    user_id = update.effective_user.id
    
    if not subscription_id:
        await update.message.reply_text("❌ Ошибка: Потерян ID подписки. Начните заново.")
        return ConversationHandler.END
    
    containers_to_remove = normalize_containers(update.message.text)
    if not containers_to_remove:
        await update.message.reply_text(
            "Не найдено корректных номеров контейнеров (формат XXXU1234567). "
            "Попробуйте снова или введите /cancel."
        )
        return AWAIT_REMOVE_INPUT

    removed_count = 0
    skipped_count = 0
    for container in containers_to_remove:
        success = await remove_container_from_subscription(subscription_id, container, user_id)
        if success:
            removed_count += 1
        else:
            skipped_count += 1

    response_lines = [f"✅ **Операция завершена!**"]
    if removed_count > 0:
        response_lines.append(f"Удалено контейнеров: {removed_count}")
    if skipped_count > 0:
        response_lines.append(f"Не найдены в подписке (пропущено): {skipped_count}")
        
    await update.message.reply_text("\n".join(response_lines), parse_mode="Markdown")

    sub = await get_subscription_details(subscription_id, user_id)
    if not sub:
        await update.message.reply_text("❌ Ошибка: подписка не найдена.")
        return ConversationHandler.END

    keyboard = []
    text = (
        f"Выберите контейнеры для **поштучного** удаления из подписки *{sub.subscription_name}*:\n\n"
        "Или отправьте **список** контейнеров (через пробел/запятую) для удаления.\n\n"
        "Для отмены введите /cancel."
    )
    
    if sub.containers:
        for container in sub.containers:
            keyboard.append([
                InlineKeyboardButton(f"🗑️ {container}", callback_data=f"sub_rem_do_{sub.id}_{container}")
            ])
    else:
        text = "Все контейнеры удалены.\n\nДля отмены введите /cancel."
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_rem_back_{sub.id}")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    return AWAIT_REMOVE_INPUT

async def remove_containers_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает нажатие "Назад" в диалоге удаления.
    Вызывает subscription_menu_callback и завершает диалог.
    """
    query = update.callback_query
    if not query or not query.data or not query.from_user or not context.user_data:
        if query: await query.answer()
        return ConversationHandler.END

    subscription_id = int(query.data.split("_")[-1])
    
    # Убедимся, что ID совпадает
    if subscription_id != context.user_data.get('sub_id_to_edit'):
        await query.answer("❌ Ошибка сессии.", show_alert=True)
        return ConversationHandler.END

    # --- 🐞 НАЧАЛО ИСПРАВЛЕНИЯ (AttributeError: 'data' can't be set) 🐞 ---
    
    # 1. Получаем свежие данные
    sub = await get_subscription_details(subscription_id, query.from_user.id)
    if not sub:
        await query.edit_message_text("❌ Ошибка: подписка не найдена.")
        return ConversationHandler.END
        
    # 2. Копируем логику отрисовки из subscription_menu_callback
    email_list = [sub_email.email.email for sub_email in sub.target_emails]
    emails_text = '`' + '`, `'.join(email_list) + '`' if email_list else 'Только в Telegram'
    status_text = 'Активна ✅' if sub.is_active is True else 'Неактивна ⏸️'
    containers_count = len(sub.containers) if sub.containers is not None else 0
    text = (
        f"⚙️ *Управление подпиской:*\n"
        f"*{sub.subscription_name}* `({sub.id})`\n\n"
        f"Статус: {status_text}\n"
        f"Время отчета: {sub.notification_time.strftime('%H:%M')}\n" 
        f"Контейнеров: {containers_count} шт.\n"
        f"Email для отчетов: {emails_text}"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Показать контейнеры", callback_data=f"sub_show_{sub.id}")],
        [
            InlineKeyboardButton("➕ Добавить контейнеры", callback_data=f"sub_add_ctn_{sub.id}"),
            InlineKeyboardButton("➖ Удалить контейнеры", callback_data=f"sub_rem_ctn_{sub.id}")
        ],
        [InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"sub_delete_{sub.id}")],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data="sub_back_to_list")]
    ]
    
    # 3. Редактируем сообщение, возвращая его в меню
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Меню подписки не изменилось, пропуск редактирования.")
        else:
            logger.error(f"Ошибка в remove_containers_back: {e}", exc_info=True)

    # 4. Чистим user_data и выходим из диалога
    context.user_data.clear()
    return ConversationHandler.END
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ 🏁 ---

async def remove_containers_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Отмена диалога удаления. Возвращает пользователя в главное меню подписки.
    """
    if not context.user_data or not update.effective_user:
         if update.message:
             await update.message.reply_text("Отмена.")
         return ConversationHandler.END
         
    subscription_id = context.user_data.get('sub_id_to_edit')
    user_id = update.effective_user.id
    
    if update.message:
        await update.message.reply_text("Отмена. Возвращаю в меню подписки...")

    context.user_data.clear()
    
    if not subscription_id:
        return ConversationHandler.END

    # "Перерисовываем" главное меню подписки
    sub = await get_subscription_details(subscription_id, user_id)
    if not sub:
        if update.message:
            await update.message.reply_text("❌ Ошибка: подписка не найдена.")
        return ConversationHandler.END
        
    email_list = [sub_email.email.email for sub_email in sub.target_emails]
    emails_text = '`' + '`, `'.join(email_list) + '`' if email_list else 'Только в Telegram'
    status_text = 'Активна ✅' if sub.is_active is True else 'Неактивна ⏸️'
    containers_count = len(sub.containers) if sub.containers is not None else 0
    text = (
        f"⚙️ *Управление подпиской:*\n"
        f"*{sub.subscription_name}* `({sub.id})`\n\n"
        f"Статус: {status_text}\n"
        f"Время отчета: {sub.notification_time.strftime('%H:%M')}\n" 
        f"Контейнеров: {containers_count} шт.\n"
        f"Email для отчетов: {emails_text}"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Показать контейнеры", callback_data=f"sub_show_{sub.id}")],
        [
            InlineKeyboardButton("➕ Добавить контейнеры", callback_data=f"sub_add_ctn_{sub.id}"),
            InlineKeyboardButton("➖ Удалить контейнеры", callback_data=f"sub_rem_ctn_{sub.id}")
        ],
        [InlineKeyboardButton("🗑️ Удалить подписку", callback_data=f"sub_delete_{sub.id}")],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data="sub_back_to_list")]
    ]
    
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    return ConversationHandler.END


# --- CONVERSATION HANDLER ДЛЯ ДОБАВЛЕНИЯ КОНТЕЙНЕРОВ ---

async def add_containers_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    
    if not query or not query.data or not query.from_user:
        if query:
            await query.answer("Ошибка: не удалось получить данные. Попробуйте снова.")
        return ConversationHandler.END
    
    if context.user_data:
        context.user_data.clear()
        
    subscription_id = int(query.data.split("_")[-1])
    context.user_data['sub_id_to_edit'] = subscription_id
    
    if query.message:
        context.user_data['menu_message_id'] = query.message.message_id
    
    await query.answer()
    await query.edit_message_text(
        "Отправьте номера контейнеров (один или несколько, через пробел/запятую), "
        "которые вы хотите **добавить** в эту подписку.\n\n"
        "Или введите /cancel для отмены."
    )
    return ASK_ADD_CONTAINERS

async def add_containers_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (
        not update.message or not update.message.text or
        not context.user_data or not update.effective_user
    ):
        return ConversationHandler.END
        
    subscription_id = context.user_data.get('sub_id_to_edit')
    user_id = update.effective_user.id
    
    if not subscription_id:
        await update.message.reply_text("❌ Ошибка: Потерян ID подписки. Начните заново.")
        return ConversationHandler.END

    # 1. Парсим контейнеры
    containers_to_add = normalize_containers(update.message.text)
    if not containers_to_add:
        await update.message.reply_text(
            "Не найдено корректных номеров контейнеров (формат XXXU1234567). "
            "Попробуйте снова или введите /cancel."
        )
        return ASK_ADD_CONTAINERS # Остаемся в том же состоянии

    # 2. Добавляем в БД
    added_count = 0
    skipped_count = 0
    for container in containers_to_add:
        success = await add_container_to_subscription(subscription_id, container, user_id)
        if success:
            added_count += 1
        else:
            skipped_count += 1 # (Вероятно, такой уже был)

    # 3. Отправляем отчет
    response_lines = [f"✅ **Операция завершена!**"]
    if added_count > 0:
        response_lines.append(f"Добавлено новых контейнеров: {added_count}")
    if skipped_count > 0:
        response_lines.append(f"Уже были в подписке (пропущено): {skipped_count}")
        
    await update.message.reply_text("\n".join(response_lines), parse_mode="Markdown")

    # 4. Удаляем сообщение "Отправьте номера..." (которое было меню)
    menu_message_id = context.user_data.get('menu_message_id')
    chat_id = update.effective_chat.id if update.effective_chat else None
    
    if menu_message_id and chat_id and context.bot:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=menu_message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить старое меню: {e}")

    # 5. Вызываем my_subscriptions_command, чтобы показать пользователю
    #    общий список его подписок.
    try:
        # Передаем update (с .message), чтобы функция могла ответить
        await my_subscriptions_command(update, context) 
    except Exception as e:
        logger.error(f"Не удалось вернуть пользователя в /my_subscriptions: {e}", exc_info=True)
        if chat_id:
             await context.bot.send_message(chat_id, "Воспользуйтесь /my_subscriptions для возврата в меню.")

    # 6. Чистим и выходим
    context.user_data.clear()
    return ConversationHandler.END

async def add_containers_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога добавления."""
    if context.user_data:
        context.user_data.clear()
    if update.message:
        await update.message.reply_text("Добавление контейнеров отменено.")
    
    if update.effective_user:
        logger.info(f"Пользователь {update.effective_user.id} отменил добавление контейнеров.")
    return ConversationHandler.END

# --- ОБНОВЛЕННЫЕ ФУНКЦИИ РЕГИСТРАЦИИ ХЕНДЛЕРОВ ---

def get_subscription_management_handlers():
    """
    Возвращает список ОБЫЧНЫХ CallbackQuery-хендлеров для управления подписками.
    """
    return [
        CommandHandler("my_subscriptions", my_subscriptions_command),
        CallbackQueryHandler(subscription_menu_callback, pattern="^sub_menu_"),
        CallbackQueryHandler(show_containers_callback, pattern="^sub_show_"),
        
        CallbackQueryHandler(delete_subscription_callback, pattern="^sub_delete_"),
        CallbackQueryHandler(delete_subscription_confirm_yes, pattern="^sub_delete_confirm_yes_"),
        
        CallbackQueryHandler(back_to_subscriptions_list_callback, pattern="^sub_back_to_list$"),
    ]

def get_add_containers_conversation_handler() -> ConversationHandler:
    """
    Возвращает ДИАЛОГ (ConversationHandler) для ДОБАВЛЕНИЯ контейнеров.
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_containers_start, pattern="^sub_add_ctn_")
        ],
        states={
            ASK_ADD_CONTAINERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_containers_receive)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", add_containers_cancel)
        ],
        per_message=False,
        persistent=False,
        name="add_containers_conversation"
    )

def get_remove_containers_conversation_handler() -> ConversationHandler:
    """
    Возвращает ДИАЛОГ (ConversationHandler) для УДАЛЕНИЯ контейнеров.
    Принимает либо нажатие кнопки (поштучно), либо список (текстом).
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(remove_containers_start, pattern="^sub_rem_ctn_")
        ],
        states={
            AWAIT_REMOVE_INPUT: [
                # Обработчик для поштучного удаления
                CallbackQueryHandler(remove_container_do_conversation, pattern="^sub_rem_do_"),
                # Обработчик для удаления списком
                MessageHandler(filters.TEXT & ~filters.COMMAND, remove_containers_by_list),
                # Обработчик кнопки "Назад"
                CallbackQueryHandler(remove_containers_back, pattern="^sub_rem_back_")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", remove_containers_cancel)
        ],
        per_message=False,
        persistent=False,
        name="remove_containers_conversation"
    )