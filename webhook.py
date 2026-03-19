"""
Webhook handler for Telegram bot on Railway – with test endpoint.
"""

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
import os
import sys

from telegram_bot import build_application

app = FastAPI()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot_app = None

@app.on_event("startup")
async def startup_event():
    global bot_app
    if not BOT_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        sys.exit(1)

    public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if not public_domain:
        print("❌ RAILWAY_PUBLIC_DOMAIN not set. Generate a domain in Railway Networking.")
        sys.exit(1)

    webhook_url = f"https://{public_domain}/webhook"
    print(f"🌐 Setting webhook to: {webhook_url}")

    bot_app = await build_application()

    # Delete any existing webhook first
    await bot_app.bot.delete_webhook()
    await bot_app.bot.set_webhook(webhook_url)
    print(f"✅ Webhook set successfully to {webhook_url}")

@app.on_event("shutdown")
async def shutdown_event():
    if bot_app:
        print("🧹 Deleting webhook...")
        await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, bot_app.bot)
    await bot_app.process_update(update)
    return "ok"

# Simple GET endpoint to check if the server is alive
@app.get("/")
async def root():
    return {"status": "alive", "message": "Bot webhook server is running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
