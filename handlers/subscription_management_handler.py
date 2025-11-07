# handlers/subscription_management_handler.py
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

logger = get_logger(__name__)

# --- НОВЫЕ СОСТОЯНИЯ ДЛЯ ДИАЛОГА ДОБАВЛЕНИЯ ---
(ASK_ADD_CONTAINERS,) = range(10, 11) # Используем диапазон, чтобы не пересекаться с другими

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
    
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif update.callback_query:
         if update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def subscription_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    await query.answer()
    subscription_id = int(query.data.split("_")[-1])
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
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


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


# --- НОВЫЕ ФУНКЦИИ ДЛЯ УДАЛЕНИЯ КОНТЕЙНЕРОВ (ИНТЕРАКТИВНОЕ МЕНЮ) ---

async def remove_containers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает меню для удаления контейнеров (нажатие на "➖ Удалить контейнеры").
    """
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
        
    subscription_id = int(query.data.split("_")[-1])
    user_id = query.from_user.id
    
    sub = await get_subscription_details(subscription_id, user_id)
    
    if not sub:
        await query.answer("❌ Ошибка: подписка не найдена.", show_alert=True)
        return
        
    await query.answer()
    keyboard = []
    text = f"Выберите контейнеры для удаления из подписки *{sub.subscription_name}*:\n"
    
    if sub.containers:
        for container in sub.containers:
            # callback_data: sub_rem_do_{id подписки}_{номер контейнера}
            keyboard.append([
                InlineKeyboardButton(f"🗑️ {container}", callback_data=f"sub_rem_do_{sub.id}_{container}")
            ])
    else:
        text += "\nВ этой подписке уже нет контейнеров."
        
    # Кнопка "Назад" в главное меню подписки
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_menu_{sub.id}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def remove_container_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие на кнопку с контейнером для удаления.
    """
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
        
    # --- 🐞 ИСПРАВЛЕНИЕ БАГА (от 07.11) 🐞 ---
    parts = query.data.split("_")
    # Ожидаем ['sub', 'rem', 'do', 'id', 'container']
    if len(parts) < 5: 
        logger.warning(f"Ошибка парсинга callback_data в remove_container_do: {query.data}")
        await query.answer("❌ Ошибка данных.", show_alert=True)
        return
        
    try:
        # ID - это 4-й элемент (индекс 3)
        subscription_id = int(parts[3])
        # Номер контейнера - это все, что идет после
        container_number = "_".join(parts[4:])
        user_id = query.from_user.id
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ БАГА 🏁 ---
            
        # 1. Удаляем контейнер из БД
        success = await remove_container_from_subscription(subscription_id, container_number, user_id)
        
        if not success:
            await query.answer(f"❌ Не удалось удалить {container_number}.", show_alert=True)
            return
            
        await query.answer(f"✅ {container_number} удален.")
        
        # 2. Обновляем меню (показываем оставшиеся контейнеры)
        sub = await get_subscription_details(subscription_id, user_id)
        if not sub:
            await query.edit_message_text("❌ Ошибка: подписка не найдена.")
            return

        keyboard = []
        text = f"Выберите контейнеры для удаления из подписки *{sub.subscription_name}*:\n"
        
        if sub.containers:
            for container in sub.containers:
                keyboard.append([
                    InlineKeyboardButton(f"🗑️ {container}", callback_data=f"sub_rem_do_{sub.id}_{container}")
                ])
        else:
            text += "\nВсе контейнеры удалены."
            
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"sub_menu_{sub.id}")])
        
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception as e:
            logger.info(f"Ошибка редактирования сообщения (возможно, не изменилось): {e}")
            pass
            
    except Exception as e:
        logger.error(f"Ошибка в remove_container_do: {e}", exc_info=True)
        await query.answer("❌ Произошла внутренняя ошибка.", show_alert=True)

# --- НОВЫЙ CONVERSATION HANDLER ДЛЯ ДОБАВЛЕНИЯ КОНТЕЙНЕРОВ ---

async def add_containers_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начало диалога добавления контейнеров (нажатие на "➕ Добавить контейнеры").
    """
    query = update.callback_query
    
    if not query or not query.data or not query.from_user:
        if query:
            await query.answer("Ошибка: не удалось получить данные. Попробуйте снова.")
        return ConversationHandler.END
    
    # --- 🐞 НАЧАЛО ИСПРАВЛЕНИЯ БАГА (от 07.11) 🐞 ---
    # Нельзя ПЕРЕЗАПИСАТЬ user_data, его можно только ОЧИСТИТЬ.
    if context.user_data:
        context.user_data.clear()
    # --- 🏁 КОНЕЦ ИСПРАВЛЕНИЯ БАГА 🏁 ---
        
    subscription_id = int(query.data.split("_")[-1])
    # Теперь мы безопасно добавляем ключ в пустой (или существующий) user_data
    context.user_data['sub_id_to_edit'] = subscription_id
    
    await query.answer()
    await query.edit_message_text(
        "Отправьте номера контейнеров (один или несколько, через пробел/запятую), "
        "которые вы хотите **добавить** в эту подписку.\n\n"
        "Или введите /cancel для отмены."
    )
    return ASK_ADD_CONTAINERS

async def add_containers_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Получает текст с контейнерами, добавляет их в подписку.
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

    # 4. Чистим и выходим
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
        CallbackQueryHandler(back_to_subscriptions_list_callback, pattern="^sub_back_to_list$"),
        
        # --- НОВЫЕ ХЕНДЛЕРЫ ДЛЯ УДАЛЕНИЯ ---
        CallbackQueryHandler(remove_containers_menu, pattern="^sub_rem_ctn_"),
        CallbackQueryHandler(remove_container_do, pattern="^sub_rem_do_"),
    ]

def get_add_containers_conversation_handler() -> ConversationHandler:
    """
    Возвращает ДИАЛОГ (ConversationHandler) для добавления контейнеров.
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
        # Не сохраняем состояние при перезапуске
        persistent=False,
        name="add_containers_conversation"
    )