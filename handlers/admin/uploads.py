# handlers/admin/uploads.py
import os
import re
import asyncio
from pathlib import Path
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    MessageHandler, CallbackQueryHandler, filters
)

from config import ADMIN_CHAT_ID
from logger import get_logger
from services.dislocation_importer import process_dislocation_file, DOWNLOAD_DIR as DISLOCATION_DOWNLOAD_FOLDER 
from services.terminal_importer import (
    import_train_from_excel, 
    extract_train_code_from_filename, 
    process_terminal_report_file,
    _collect_containers_from_excel 
)
from services.file_utils import save_temp_file_async
from utils.notify import notify_admin

# --- ✅ ОБНОВЛЕННЫЕ ИМПОРТЫ ---
from queries.train_queries import (
    upsert_train_on_upload, 
    get_first_container_in_train,
    get_train_client_summary_by_code,
    update_train_status_from_tracking_data,
    get_train_details,
    get_latest_active_tracking_for_train # <--- "Умный" поиск дислокации
)
# Импортируем сессию, чтобы передать ее в update_train_status
from db import SessionLocal 
from models import Train 

logger = get_logger(__name__)

# Состояния для диалога
ASK_OVERLOAD_CONFIRM, ASK_STATION_NAME = range(2)

TERMINAL_REPORT_PATTERN = r'A-Terminal.*\.xlsx$'


async def upload_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информирует администратора о способе загрузки файлов."""
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message:
        return

    text = (
        "**Инструкция по загрузке файлов:**\n\n"
        "1. **Файлы дислокации (103):**\n"
        "   - Имя файла должно начинаться с `103_`.\n"
        "2. **Файлы поезда (KXX-YYY):**\n"
        "   - Имя файла должно содержать код поезда (например, `КП К25-073 Селятино.xlsx`).\n"
        "3. **Отчет терминала (A-Terminal):**\n"
        "   - Имя файла должно содержать `A-Terminal`.\n\n"
        "Отправьте Excel-файл как документ."
    )
    await update.message.reply_text(text, parse_mode='Markdown')


# --- ✅ ОБНОВЛЕННАЯ ФУНКЦИЯ: ФОРМАТИРОВАНИЕ ОТЧЕТА ---
async def _build_and_send_report(
    message: Message,
    terminal_train_number: str
):
    """
    Собирает все данные по поезду (Train, Сводка, Контрольный КТК) 
    и отправляет финальный отчет.
    """
    logger.info(f"[TrainReport] Собираю отчет для {terminal_train_number}...")
    
    # 1. Получаем основную инфу о поезде (включая дислокацию)
    train_details = await get_train_details(terminal_train_number)
    
    # 2. Получаем сводку по клиентам
    client_summary = await get_train_client_summary_by_code(terminal_train_number)
    
    # 3. Получаем контрольный контейнер
    control_container = await get_first_container_in_train(terminal_train_number)

    # --- Форматируем отчет ---
    lines = [f"🚆 **Поезд:** `{terminal_train_number}`"]
    
    if train_details:
        lines.append(f"**Дата отправления:** `{train_details.departure_date.strftime('%d.%m.%Y') if train_details.departure_date else 'н/д'}`")
        lines.append(f"**Станция назначения:** `{train_details.destination_station or 'н/д'}`")
        lines.append(f"**Станция перегруза:** `{train_details.overload_station_name or 'Нет'}`")
        lines.append("-----")
        
        # --- ✅ ЛОГИКА ОТОБРАЖЕНИЯ ДАТЫ ПЕРЕГРУЗА ---
        # Дата перегруза (покажется только если она была установлена импортером дислокации)
        if train_details.overload_date:
            try:
                # astimezone(None) преобразует UTC (если оно в БД) в локальное время сервера
                local_time = train_details.overload_date.astimezone(None)
                lines.append(f"**Дата перегруза:** `{local_time.strftime('%d.%m.%Y %H:%M')}`")
            except (ValueError, AttributeError):
                # На случай, если время в БД не имеет таймзоны
                lines.append(f"**Дата перегруза:** `{train_details.overload_date.strftime('%d.%m.%Y %H:%M')}`")
        elif train_details.overload_station_name:
             # Если станция задана, но даты нет
            lines.append(f"**Дата перегруза:** `(Ожидает прибытия на станцию)`")
        else:
            # Если станция не задана
             lines.append(f"**Дата перегруза:** `(Не указана)`")
        # ---
        
        lines.append(f"**Операция с поездом:** `{train_details.last_operation or 'н/д'}`") 
        lines.append(f"**Станция операции:** `{train_details.last_known_station or 'н/д'}`")
        lines.append(f"**Дата и время операции:** `{train_details.last_operation_date.strftime('%d.%m.%Y %H:%M') if train_details.last_operation_date else 'н/д'}`")
    else:
        lines.append("_(Не удалось загрузить детали поезда из БД `Train`)_")
        
    lines.append("───")
    lines.append("📦 **Сводка по клиентам:**")
    if client_summary:
        for client, count in client_summary.items():
            lines.append(f"• {client} — *{count}*")
    else:
        lines.append("_(Сводка не найдена)_")
        
    lines.append("───")
    lines.append(f"**Контрольный контейнер:** `{control_container or 'н/д'}`")
    
    # Убедимся, что message - это Message, а не None
    if message:
        await message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        logger.error("[TrainReport] Не удалось отправить отчет, 'message' is None")


# --- ✅ ОБНОВЛЕННАЯ ФУНКЦИЯ: ОБЩАЯ ЛОГИКА ЗАВЕРШЕНИЯ ---
async def _finish_train_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    overload_station: str | None,
    overload_date: datetime | None # <--- Теперь он ВСЕГДА будет None при вызове
) -> int:
    """
    Общая функция, которая выполняет все шаги и отправляет отчет.
    """
    if not context.user_data or 'train_file_path' not in context.user_data:
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Ошибка сессии. Пожалуйста, загрузите файл заново.")
        return ConversationHandler.END

    dest_path = context.user_data['train_file_path']
    train_code = context.user_data['train_code']
    admin_id = context.user_data['admin_id']
    container_count = context.user_data['container_count']

    # 1. Обновляем TerminalContainer (данные о клиентах)
    try:
        await import_train_from_excel(str(dest_path))
        logger.info(f"[TrainUpload] Шаг 1/4: TerminalContainer для {train_code} обновлен.")
    except Exception as e:
        logger.error(f"❌ Ошибка импорта в `TerminalContainer`: {e}", exc_info=True)

    # 2. Создаем/Обновляем запись в 'Train' (с инфой о перегрузе, но БЕЗ ДАТЫ)
    await upsert_train_on_upload(
        terminal_train_number=train_code,
        container_count=container_count,
        admin_id=admin_id,
        overload_station_name=overload_station,
        overload_date=None # <--- ✅ ДАТА НЕ УСТАНАВЛИВАЕТСЯ ПРИ ЗАГРУЗКЕ
    )
    logger.info(f"[TrainUpload] Шаг 2/4: Таблица `Train` для {train_code} обновлена (перегруз: {overload_station or 'Нет'}).")

    # 3. Находим АКТИВНУЮ дислокацию (с номером поезда РЖД)
    logger.info(f"[TrainUpload] Шаг 3/4: Ищу АКТИВНУЮ дислокацию для {train_code}...")
    tracking_data = await get_latest_active_tracking_for_train(train_code)
    
    if tracking_data:
        # 4. Обновляем 'Train' данными дислокации
        # (Эта функция сама откроет сессию и выполнит логику проверки даты перегруза)
        async with SessionLocal() as session:
             # Передаем сессию, т.к. update_train_status... ожидает ее
            await update_train_status_from_tracking_data(train_code, tracking_data, session)
            await session.commit()
        logger.info(f"[TrainUpload] Шаг 4/4: Статус поезда {train_code} обновлен дислокацией.")
    else:
        logger.warning(f"[TrainUpload] Шаг 4/4: АКТИВНАЯ дислокация (с поездом РЖД) для {train_code} не найдена.")

    # 5. Отправляем отчет
    message_to_reply_to = None
    if update.callback_query:
        await update.callback_query.delete_message()
        message_to_reply_to = update.callback_query.message
    elif update.message:
        message_to_reply_to = update.message

    if message_to_reply_to:
        await _build_and_send_report(message_to_reply_to, train_code)
    else:
        logger.error(f"[TrainUpload] Не удалось найти сообщение для ответа по поезду {train_code}")


    # Очистка
    if os.path.exists(dest_path): os.remove(dest_path)
    context.user_data.clear()
    return ConversationHandler.END


# --- ДИАЛОГ ЗАГРУЗКИ (handle_admin_document_entry - без изменений) ---

async def handle_admin_document_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Точка входа в диалог. 
    Обрабатывает дислокацию/терминал сразу ИЛИ запускает диалог для поезда.
    """
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message or not update.message.document:
        return ConversationHandler.END
    
    document = update.message.document
    original_filename = document.file_name
    
    if not original_filename or not original_filename.lower().endswith('.xlsx'):
        await update.message.reply_text("Пожалуйста, отправьте файл в формате .xlsx.")
        return ConversationHandler.END

    file_id = document.file_id
    dest_folder = DISLOCATION_DOWNLOAD_FOLDER 
    
    await update.message.reply_text(f"📥 Получен файл: **{original_filename}**", parse_mode='Markdown')
    
    dest_path = await save_temp_file_async(
        context.bot, 
        file_id, 
        original_filename, 
        dest_folder
    )
    
    if not dest_path:
        await notify_admin(f"❌ Ошибка: Не удалось скачать файл {original_filename}.", silent=False)
        return ConversationHandler.END

    filename_lower = original_filename.lower()

    # --- 1. Обработка файла дислокации (103) ---
    if filename_lower.startswith('103_'):
        logger.info(f"📥 [Admin Upload] Начало обработки файла дислокации: {original_filename}")
        try:
            processed_count = await process_dislocation_file(str(dest_path))
            await update.message.reply_text(f"✅ Обработка дислокации завершена. Обновлено записей: **{processed_count}**.", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке файла дислокации: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке файла дислокации: {e}")
        
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END

    # --- 2. Обработка отчета терминала (A-Terminal) ---
    elif re.search(TERMINAL_REPORT_PATTERN, original_filename, re.IGNORECASE):
        logger.info(f"📥 [Admin Upload] Начало обработки отчета терминала: {original_filename}")
        try:
            stats = await process_terminal_report_file(str(dest_path))
            await update.message.reply_text(
                f"✅ Отчет терминала **{original_filename}** обработан.\n"
                f"Контейнеров добавлено: **{stats.get('added', 0)}**\n"
                f"Обновлено: **{stats.get('updated', 0)}**",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"❌ [Admin Upload] Ошибка при обработке отчета терминала: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Критическая ошибка при обработке отчета терминала: {e}")
            
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END
            
    # --- 3. Обработка файла поезда (KXX-YYY) ---
    elif extract_train_code_from_filename(original_filename):
        train_code = extract_train_code_from_filename(original_filename)
        logger.info(f"📥 [Admin Upload] Обнаружен файл поезда: {train_code}. Запускаю диалог перегруза.")
        
        container_map = await _collect_containers_from_excel(str(dest_path))
        container_count = len(container_map)
        if container_count == 0:
             await update.message.reply_text(f"⚠️ В файле поезда {train_code} не найдено ни одного контейнера. Импорт отменен.")
             if os.path.exists(dest_path): os.remove(dest_path)
             return ConversationHandler.END

        context.user_data['train_file_path'] = dest_path
        context.user_data['train_code'] = train_code
        context.user_data['admin_id'] = update.effective_user.id
        context.user_data['container_count'] = container_count 

        keyboard = [
            [
                InlineKeyboardButton("✅ Да, с перегрузом", callback_data="overload_yes"),
                InlineKeyboardButton("❌ Нет, обычная загрузка", callback_data="overload_no")
            ]
        ]
        await update.message.reply_text(
            f"Поезд **{train_code}** ({container_count} конт.)\n\n"
            f"Этот поезд отправлен с перегрузом в пути следования?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return ASK_OVERLOAD_CONFIRM
            
    else:
        await update.message.reply_text("⚠️ Не удалось определить тип файла (103_, KXX-YYY, или A-Terminal).")
        if os.path.exists(dest_path): os.remove(dest_path)
        return ConversationHandler.END

# --- (handle_overload_confirm - без изменений) ---
async def handle_overload_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ответ (Да/Нет) на вопрос о перегрузе."""
    query = update.callback_query
    await query.answer("Принято, обрабатываю...")
    
    choice = query.data
    
    if choice == "overload_no":
        logger.info(f"Выбрана обычная загрузка для поезда {context.user_data.get('train_code')}")
        # Вызываем общую функцию, передавая "Нет" для перегруза
        return await _finish_train_upload(
            update, 
            context, 
            overload_station=None, 
            overload_date=None
        )
        
    elif choice == "overload_yes":
        logger.info(f"Поезд {context.user_data.get('train_code')} помечен как 'с перегрузом'. Запрашиваю станцию.")
        await query.edit_message_text(
            f"Поезд **{context.user_data.get('train_code')}**.\n\n"
            f"Пожалуйста, введите **название станции перегруза**:"
            f"\n(Или /cancel для отмены)",
            parse_mode='Markdown'
        )
        return ASK_STATION_NAME

    return ConversationHandler.END

# --- ✅ ОБНОВЛЕННЫЙ `handle_overload_station_name` ---
async def handle_overload_station_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает станцию, выполняет оба импорта и завершает диалог."""
    if not update.message or not update.message.text or not context.user_data:
        return ConversationHandler.END
        
    station_name = update.message.text.strip()
    
    await update.message.reply_text(f"Принято: станция перегруза **{station_name}**. Начинаю обработку...", parse_mode="Markdown")

    # --- ✅ ИЗМЕНЕНИЕ: Мы передаем overload_date=None ---
    # Дата будет установлена позже, когда дислокация совпадет
    return await _finish_train_upload(
        update, 
        context, 
        overload_station=station_name, 
        overload_date=None 
    )


async def cancel_overload_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет диалог и удаляет временный файл."""
    if context.user_data:
        dest_path = context.user_data.get('train_file_path')
        if dest_path and os.path.exists(dest_path):
            os.remove(dest_path)
        context.user_data.clear()
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Загрузка отменена.")
    elif update.message:
        await update.message.reply_text("❌ Загрузка отменена.")
        
    return ConversationHandler.END


def get_admin_upload_conversation_handler():
    """Возвращает ConversationHandler для загрузки файлов."""
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Chat(ADMIN_CHAT_ID) & filters.Document.FileExtension("xlsx"), 
                handle_admin_document_entry
            )
        ],
        states={
            ASK_OVERLOAD_CONFIRM: [
                CallbackQueryHandler(handle_overload_confirm, pattern="^overload_(yes|no)$")
            ],
            ASK_STATION_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_overload_station_name)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_overload_dialog)],
    )