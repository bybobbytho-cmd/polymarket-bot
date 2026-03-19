"""
Telegram Bot for Polymarket – Webhook version with minimal handlers for testing.
"""

import os
import requests
import json
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")  # optional

# Simple handlers for testing
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot is alive and working via webhook!")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commands:\n/start\n/ping\n/help")

# Build application function (used by webhook.py)
async def build_application():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("help", help_command))
    await app.initialize()
    await app.start()
    return app

# For local testing (if you ever run directly)
if __name__ == "__main__":
    print("This bot is designed to run via webhook.py on Railway.")
