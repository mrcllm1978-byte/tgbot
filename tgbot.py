import re
import sqlite3
import logging
import os
import asyncio
from telegram import Update
from telegram.error import BadRequest
from telegram.helpers import escape
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Admin user IDs - update with your admin user IDs
ADMINS = set(6657831903)

# Database setup
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS commands (command TEXT PRIMARY KEY, response TEXT)''')
    # Add username column if not exists (for migration)
    try:
        c.execute('ALTER TABLE users ADD COLUMN username TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()

# Token loading

def get_bot_token():
    return os.getenv('BOT_TOKEN')

# Database functions
def get_balance(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_balance(user_id, amount):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, balance) VALUES (?, ?)', (user_id, amount))
    conn.commit()
    conn.close()

def update_user_info(user_id, username):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, balance, username) VALUES (?, COALESCE((SELECT balance FROM users WHERE user_id = ?), 0), ?)', (user_id, user_id, username))
    conn.commit()
    conn.close()

def get_user_id_by_username(username):
    username = (username or '').strip().lstrip('@')
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)', (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_balances():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT user_id, balance, username FROM users')
    results = c.fetchall()
    conn.close()
    return results

COMMAND_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
RESERVED_COMMANDS = {
    'start', 'help', 'bal', 'ded', 'add', 'sum', 'pricelist',
    'addcommand', 'editcommand', 'deletecommand', 'listcommands', 'commands'
}

def normalize_command_name(command: str) -> str:
    if not command:
        return ''
    command = command.strip().lstrip('/').split('@')[0].lower()
    return command


def is_valid_command_name(command: str) -> bool:
    return bool(COMMAND_NAME_RE.fullmatch(command))


def is_reserved_command(command: str) -> bool:
    return command in RESERVED_COMMANDS


def add_custom_command(command, response):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO commands (command, response) VALUES (?, ?)', (normalize_command_name(command), response))
    conn.commit()
    conn.close()


def get_custom_command(command):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT response FROM commands WHERE command = ?', (normalize_command_name(command),))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def get_first_bot_command_text(message):
    if not message or not message.entities:
        return None
    for entity in message.entities:
        if entity.type == 'bot_command':
            start = entity.offset
            end = start + entity.length
            return message.text[start:end]
    return None

async def reply_html(update: Update, text: str):
    try:
        return await update.message.reply_text(text, parse_mode='HTML', disable_web_page_preview=True)
    except BadRequest:
        return await update.message.reply_text(escape(text), disable_web_page_preview=True)


def schedule_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, message, delay: int = 180):
    # Schedule deletion of bot's reply message
    if message:
        chat_id = None
        if update and getattr(update, 'effective_chat', None):
            chat_id = update.effective_chat.id
        elif getattr(message, 'chat_id', None) is not None:
            chat_id = message.chat_id

        if chat_id is not None:
            logger.info('Scheduling deletion of bot reply message %s in chat %s after %s seconds', message.message_id, chat_id, delay)
            asyncio.create_task(delete_message_after_delay(context.bot, chat_id, message.message_id, delay))

    # Schedule deletion of user's command message (only if bot can delete messages)
    if update and update.message:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is not None and can_delete_messages(context.bot, chat_id):
            logger.info('Scheduling deletion of user command message %s in chat %s after %s seconds', update.message.message_id, chat_id, delay)
            asyncio.create_task(delete_message_after_delay(context.bot, chat_id, update.message.message_id, delay))


def get_all_custom_commands():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT command FROM commands ORDER BY command')
    commands = [row[0] for row in c.fetchall()]
    conn.close()
    return commands


def delete_custom_command(command):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('DELETE FROM commands WHERE command = ?', (normalize_command_name(command),))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0

def is_admin(user_id):
    return user_id in ADMINS

async def can_delete_messages(bot, chat_id):
    """Check if bot can delete messages in this chat"""
    try:
        # For private chats, bots can delete their own messages but not user messages
        if chat_id > 0:  # Private chat
            return False
        
        # For groups/supergroups, check if bot is admin with delete permission
        chat_member = await bot.get_chat_member(chat_id, bot.id)
        return chat_member.status in ['administrator', 'creator'] and getattr(chat_member, 'can_delete_messages', False)
    except Exception:
        # If we can't check permissions, assume we can't delete
        return False

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    message = await update.message.reply_text("Welcome to the bot!")
    schedule_deletion(update, context, message)

async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    message = await update.message.reply_text("Your balance: ${:.2f}".format(balance))
    schedule_deletion(update, context, message)

async def ded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    try:
        if len(context.args) == 1:
            # Deduct from self
            amount = float(context.args[0])
            target_user_id = user_id
        elif len(context.args) == 2 and is_admin(user_id):
            # Admin deducting from username
            username = context.args[0]
            amount = float(context.args[1])
            target_user_id = get_user_id_by_username(username)
            if not target_user_id:
                message = await update.message.reply_text(f"User @{username} not found.")
                schedule_deletion(update, context, message)
                return
        else:
            raise ValueError("Invalid arguments")
        if amount <= 0:
            raise ValueError("Amount must be positive")
        current_balance = get_balance(target_user_id)
        new_balance = current_balance - amount
        update_balance(target_user_id, new_balance)
        logger.info("User {} deducted ${:.2f} from {}, new balance: ${:.2f}".format(user_id, amount, target_user_id, new_balance))
        message = await update.message.reply_text("Deducted ${:.2f}. New balance: ${:.2f}".format(amount, new_balance))
    except (IndexError, ValueError) as e:
        message = await update.message.reply_text("Usage: /ded <amount> or /ded <username> <amount> (admin only)")
    schedule_deletion(update, context, message)

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        message = await update.message.reply_text("Admin only.")
        schedule_deletion(update, context, message)
        return
    try:
        username = context.args[0]
        amount = float(context.args[1])
        if amount <= 0:
            raise ValueError("Amount must be positive")
        target_user_id = get_user_id_by_username(username)
        if not target_user_id:
            message = await update.message.reply_text(f"User @{username} not found.")
            schedule_deletion(update, context, message)
            return
        current_balance = get_balance(target_user_id)
        new_balance = current_balance + amount
        update_balance(target_user_id, new_balance)
        logger.info("Admin {} added ${:.2f} to {}, new balance: ${:.2f}".format(user_id, amount, target_user_id, new_balance))
        message = await update.message.reply_text("Added ${:.2f} to @{}. New balance: ${:.2f}".format(amount, username, new_balance))
    except (IndexError, ValueError):
        message = await update.message.reply_text("Usage: /add <username> <amount>")
    schedule_deletion(update, context, message)

async def sum_balances(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        message = await update.message.reply_text("Admin only.")
        schedule_deletion(update, context, message)
        return
    balances = get_all_balances()
    text = "All balances:\n" + "\n".join(["@{0}: ${1:.2f}".format(user[2] or 'unknown', user[1]) for user in balances])
    message = await update.message.reply_text(text)
    schedule_deletion(update, context, message)

async def pricelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    if update.effective_chat.type != 'private':
        message = await update.message.reply_text("Check your private message.")
        schedule_deletion(update, context, message)
        # Send to private
        pricelist_text = "Pricelist:\n- Item 1: $10\n- Item 2: $20\n- etc."  # Placeholder
        private_message = await context.bot.send_message(chat_id=update.effective_user.id, text=pricelist_text)
        schedule_deletion(update, context, private_message)
    else:
        pricelist_text = "Pricelist:\n- Item 1: $10\n- Item 2: $20\n- etc."  # Placeholder
        message = await update.message.reply_text(pricelist_text)
        schedule_deletion(update, context, message)

async def addcommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        message = await update.message.reply_text("Admin only.")
        schedule_deletion(update, context, message)
        return
    try:
        text = (update.message.text or '').strip()
        command_text = get_first_bot_command_text(update.message) or '/addcommand'
        payload = text[len(command_text):].strip()
        parts = payload.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            raise IndexError
        command = normalize_command_name(parts[0])
        response = parts[1].strip()
        if not is_valid_command_name(command) or is_reserved_command(command):
            raise ValueError
        add_custom_command(command, response)
        logger.info("Admin {} added custom command /{}".format(user_id, command))
        message = await update.message.reply_text("Added command /{}".format(command))
    except IndexError:
        message = await update.message.reply_text("Usage: /addcommand <command> <response>")
    except ValueError:
        message = await update.message.reply_text("Invalid command name. Use letters, numbers, underscores only and do not use reserved commands.")
    schedule_deletion(update, context, message)

async def editcommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        message = await update.message.reply_text("Admin only.")
        schedule_deletion(update, context, message)
        return
    try:
        text = (update.message.text or '').strip()
        command_text = get_first_bot_command_text(update.message) or '/editcommand'
        payload = text[len(command_text):].strip()
        parts = payload.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            raise IndexError
        command = normalize_command_name(parts[0])
        response = parts[1].strip()
        if not is_valid_command_name(command) or is_reserved_command(command):
            raise ValueError
        if get_custom_command(command) is None:
            message = await update.message.reply_text(f"Command /{command} does not exist.")
        else:
            add_custom_command(command, response)
            logger.info("Admin {} edited custom command /{}".format(user_id, command))
            message = await update.message.reply_text("Updated command /{}".format(command))
    except IndexError:
        message = await update.message.reply_text("Usage: /editcommand <command> <response>")
    except ValueError:
        message = await update.message.reply_text("Invalid command name. Use letters, numbers, underscores only and do not use reserved commands.")
    schedule_deletion(update, context, message)

async def deletecommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        message = await update.message.reply_text("Admin only.")
        schedule_deletion(update, context, message)
        return
    try:
        command = normalize_command_name(context.args[0])
        if delete_custom_command(command):
            logger.info("Admin {} deleted custom command /{}".format(user_id, command))
            message = await update.message.reply_text("Deleted command /{}".format(command))
        else:
            message = await update.message.reply_text(f"Command /{command} not found.")
    except IndexError:
        message = await update.message.reply_text("Usage: /deletecommand <command>")
    schedule_deletion(update, context, message)

async def listcommands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    builtin_commands = sorted(RESERVED_COMMANDS)
    custom_commands = get_all_custom_commands()
    builtin_text = "\n".join([f"/{cmd}" for cmd in builtin_commands])
    if custom_commands:
        custom_text = "\n".join([f"/{cmd}" for cmd in custom_commands])
    else:
        custom_text = "No custom commands defined yet."
    text = (
        "<b>Built-in commands</b>\n"
        "{}\n\n"
        "<b>Custom commands</b>\n"
        "{}"
    ).format(builtin_text, custom_text)
    message = await reply_html(update, text)
    schedule_deletion(update, context, message)

async def custom_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    command_text = get_first_bot_command_text(update.message) or ''
    command = normalize_command_name(command_text)
    response = get_custom_command(command)
    if response:
        message = await reply_html(update, response)
        schedule_deletion(update, context, message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_info(update.effective_user.id, update.effective_user.username)
    builtin_commands = sorted(RESERVED_COMMANDS)
    custom_commands = get_all_custom_commands()
    builtin_text = "\n".join([f"/{cmd}" for cmd in builtin_commands])
    if custom_commands:
        custom_text = "\n".join([f"/{cmd}" for cmd in custom_commands])
    else:
        custom_text = "No custom commands defined yet."
    help_text = (
        "<b>Built-in commands</b>\n"
        "{}\n\n"
        "<b>Custom commands</b>\n"
        "{}\n\n"
        "Use HTML tags like <b>, <i>, <u>, <a href=\"https://example.com\">link</a>, and <br> in command responses."
    ).format(builtin_text, custom_text)
    message = await reply_html(update, help_text)
    schedule_deletion(update, context, message)

async def delete_message_after_delay(bot, chat_id, message_id, delay):
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info('Deleted message %s from chat %s', message_id, chat_id)
    except Exception as e:
        logger.warning('Could not delete message %s from chat %s: %s', message_id, chat_id, e)
        # Don't raise the exception - just log it

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Don't send error messages to avoid cascading errors
    # The bot will continue working normally

async def main():
    init_db()
    token = get_bot_token()
    if not token:
        print("Error: Please set the BOT_TOKEN environment variable with your Telegram bot token.")
        return
    
    # Build application
    application = Application.builder().token(token).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("bal", bal))
    application.add_handler(CommandHandler("ded", ded))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("sum", sum_balances))
    application.add_handler(CommandHandler("pricelist", pricelist))
    application.add_handler(CommandHandler("addcommand", addcommand))
    application.add_handler(CommandHandler("editcommand", editcommand))
    application.add_handler(CommandHandler("deletecommand", deletecommand))
    application.add_handler(CommandHandler("listcommands", listcommands))
    application.add_handler(CommandHandler("commands", listcommands))

    # Custom commands handler
    application.add_handler(MessageHandler(filters.COMMAND, custom_command_handler))

    # Error handler
    application.add_error_handler(error_handler)

    # Start the bot using polling (suitable for development/testing)
    # For production on Railway, consider using webhooks
    logger.info("Bot started successfully")
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot polling started")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Stopping bot")
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
