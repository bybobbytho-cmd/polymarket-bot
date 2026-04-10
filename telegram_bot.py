"""
Polymarket Advisory Bot – Uses the working polymarket-oracle.
"""

import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")   # set to https://polymarket-oracle-production.up.railway.app

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set")
if not ORACLE_URL:
    print("⚠️ PRICE_ORACLE_URL not set. Bot will not work.")

def get_oracle_data(asset='btc', interval='5m'):
    try:
        resp = requests.get(f"{ORACLE_URL}/api/price/{asset}/{interval}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Oracle error: {e}")
    return None

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_oracle_data('btc', '5m')
    if not data:
        await update.message.reply_text("❌ Oracle not responding. Check PRICE_ORACLE_URL.")
        return
    # Determine cheaper side and edge
    up = data['up']
    down = data['down']
    if up < down:
        rec = "BUY UP"
        edge = (down - up) / up if up > 0 else 0
        edge_pct = edge * 100
    else:
        rec = "BUY DOWN"
        edge = (up - down) / down if down > 0 else 0
        edge_pct = edge * 100
    msg = (
        f"📈 *{data['title']}*\n"
        f"Slug: `{data['slug']}`\n\n"
        f"UP: {data['upCents']}¢\n"
        f"DOWN: {data['downCents']}¢\n\n"
        f"🎯 *Recommendation*: {rec}\n"
        f"📊 Edge: {edge_pct:.1f}% (cheaper side vs. other side)"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I use the Polymarket oracle to give you live up/down prices and recommend the cheaper side.\n\n"
        "Commands:\n"
        "/signalbtc5m – 5‑minute market\n"
        "/ping – Alive check",
        parse_mode='Markdown'
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong!")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    print("Advisory bot started. Oracle URL:", ORACLE_URL)
    app.run_polling()

if __name__ == "__main__":
    main()
