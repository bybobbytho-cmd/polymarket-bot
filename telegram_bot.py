"""
Telegram Bot for Polymarket – Debug version with extensive logging.
"""

import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# Set up logging to see everything in Railway logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    logger.error("❌ TELEGRAM_TOKEN not set!")

# Simple handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ /start received from user {update.effective_user.id}")
    await update.message.reply_text("🤖 Bot is alive! Try /echo hello")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ /echo received with args: {context.args}")
    if context.args:
        text = ' '.join(context.args)
        await update.message.reply_text(f"You said: {text}")
    else:
        await update.message.reply_text("Usage: /echo <message>")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📝 Received text: {update.message.text}")
    await update.message.reply_text(f"You said: {update.message.text}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"⚠️ Update {update} caused error {context.error}")

# Build application function
async def build_application():
    logger.info("🛠️ Building application...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("echo", echo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    await app.initialize()
    await app.start()
    logger.info("✅ Application built and started")
    return app

# For direct testing
if __name__ == "__main__":
    print("Run via webhook.py on Railway.")
