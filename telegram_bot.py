"""
Telegram Bot for Polymarket – Debug version with logging and echo.
"""

import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# Set up logging to see errors in Railway logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    logger.error("TELEGRAM_TOKEN not set!")

# Simple handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received /start from user {update.effective_user.id}")
    await update.message.reply_text("🤖 Bot is alive! Try /echo hello")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received /echo with args: {context.args}")
    if context.args:
        text = ' '.join(context.args)
        await update.message.reply_text(f"You said: {text}")
    else:
        await update.message.reply_text("Usage: /echo <message>")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")

# Build application function (used by webhook.py)
async def build_application():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("echo", echo))
    app.add_error_handler(error_handler)
    await app.initialize()
    await app.start()
    return app

# If run directly (for testing)
if __name__ == "__main__":
    print("Run via webhook.py on Railway.")
