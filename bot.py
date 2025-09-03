# bot.py
from logger import get_logger
logger = get_logger(__name__)

# We no longer need Optional for the error handler
# from typing import Optional

from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
load_dotenv()

from config import TOKEN, ADMIN_CHAT_ID
from scheduler import start_scheduler
from services.terminal_importer import check_and_process_terminal_report

# --- Imports of current handlers ---
from handlers.menu_handlers import (
    start, show_menu, reply_keyboard_handler,
    menu_button_handler, dislocation_inline_callback_handler, handle_sticker
)
from handlers.email_management_handler import get_email_management_handlers
from handlers.subscription_management_handler import get_subscription_management_handlers
from handlers.tracking_handlers import tracking_conversation_handler
from handlers.dislocation_handlers import handle_message
from handlers.admin_handlers import stats, exportstats, tracking, test_notify
from handlers.broadcast import broadcast_conversation_handler
from handlers.train_handlers import upload_train_help, handle_train_excel
from handlers.train import setup_handlers as setup_train_handlers


# <<< CORRECTION: The type hint for `update` is changed to `object` to match the library's requirement
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs all unhandled errors."""
    logger.error("❗️ An unhandled error occurred: %s", context.error, exc_info=True)


async def debug_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug handler to log all incoming updates."""
    try:
        user = update.effective_user
        uid = user.id if user else "—"
        uname = user.username if user else "—"
        txt = getattr(getattr(update, "message", None), "text", None)
        logger.info(f"[DEBUG UPDATE] from {uid} (@{uname}) type={type(update).__name__} text='{txt}'")
    except Exception:
        logger.exception("[DEBUG UPDATE] failed to log update")


async def set_bot_commands(application: Application):
    """Sets the bot commands in the Telegram menu for regular users and the administrator."""
    user_commands = [
        BotCommand("start", "Main Menu"),
        BotCommand("menu", "Show Main Menu"),
        BotCommand("my_emails", "Manage Email Addresses"),
        BotCommand("my_subscriptions", "My Subscriptions"),
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Commands for users have been set.")

    admin_commands = user_commands + [
        BotCommand("stats", "Daily stats (admin)"),
        BotCommand("exportstats", "Export all stats (admin)"),
        BotCommand("testnotify", "Test broadcast to all (admin)"),
        BotCommand("tracking", "Export all subscriptions (admin)"),
        BotCommand("broadcast", "Broadcast to all users (admin)"),
        BotCommand("train", "Report on a train (admin)"),
        BotCommand("upload_train", "Upload train Excel file (admin)"),
    ]
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))
    logger.info(f"✅ Commands for the admin (ID: {ADMIN_CHAT_ID}) have been set.")


def main():
    """Main function to run the bot."""
    logger.info("🚦 Starting the bot!")
    
    if not TOKEN:
        logger.critical("🔥 Critical Error: TELEGRAM_TOKEN is not set! The bot cannot start.")
        return

    try:
        request = HTTPXRequest(
            connect_timeout=20.0, read_timeout=60.0, write_timeout=60.0,
            pool_timeout=20.0, connection_pool_size=50,
        )
        application = Application.builder().token(TOKEN).request(request).build()

        # --- Handler Registration ---
        
        # 1. Dialogs (ConversationHandlers)
        application.add_handler(broadcast_conversation_handler)
        application.add_handler(tracking_conversation_handler()) # For creating new subscriptions
        setup_train_handlers(application)
        
        # 2. Menu and Command Handlers
        application.add_handlers(get_email_management_handlers())
        application.add_handlers(get_subscription_management_handlers())
        
        # 3. Basic Commands
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", show_menu))
        
        # 4. Admin Commands
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("exportstats", exportstats))
        application.add_handler(CommandHandler("tracking", tracking))
        application.add_handler(CommandHandler("testnotify", test_notify))
        application.add_handler(CommandHandler("upload_train", upload_train_help))
        
        # 5. Button Handlers (Callbacks)
        application.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^(start|dislocation|track_request)$"))
        application.add_handler(CallbackQueryHandler(dislocation_inline_callback_handler, pattern="^dislocation_inline$"))

        # 6. Message Handlers
        application.add_handler(MessageHandler(
            filters.Regex("^(📦 Дислокация|🔔 Задать слежение|❌ Отмена слежения)$"),
            reply_keyboard_handler
        ))
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_train_excel))
        
        # 7. Text Handler (should be one of the last)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # 8. Debug Handler (catches everything else)
        application.add_handler(MessageHandler(filters.ALL, debug_all_updates))

        # Global Error Handler
        application.add_error_handler(error_handler)

        async def post_init(app: Application):
            """Runs after the application is initialized but before polling starts."""
            logger.info("⚙️ Running post-initialization tasks...")
            await app.bot.send_message(ADMIN_CHAT_ID, "🤖 Bot has started with full subscription logic.")
            await set_bot_commands(app)
            start_scheduler(app.bot)
            await check_and_process_terminal_report()
            logger.info("✅ post_init has completed.")

        application.post_init = post_init
        
        logger.info("🤖 Bot is ready to start. Beginning polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.critical("🔥 Critical error during bot startup: %s", e, exc_info=True)


if __name__ == "__main__":
    main()