"""
Webhook handler for Telegram bot on Railway.
"""

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
import os
import uvicorn

# Import the function that builds your bot application
from telegram_bot import build_application

app = FastAPI()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot_app = None

@app.on_event("startup")
async def startup_event():
    global bot_app
    bot_app = await build_application()
    webhook_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/webhook"
    await bot_app.bot.set_webhook(webhook_url)
    print(f"✅ Webhook set to {webhook_url}")

@app.on_event("shutdown")
async def shutdown_event():
    if bot_app:
        await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, bot_app.bot)
    await bot_app.process_update(update)
    return "ok"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
