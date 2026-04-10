"""
Polymarket Advisory Bot – Uses real order book ask prices.
"""

import os
import time
import requests
import json
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set")

# ---------- Helper: get current market slug (with fallback) ----------
def get_market_slug(interval='5m'):
    period = 300 if interval == '5m' else 900
    now = int(time.time())
    # Try current window
    window_start = now - (now % period)
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return slug, data[0]
    except:
        pass
    # Fallback to previous window
    window_start -= period
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data:
            return slug, data[0]
    return None, None

# ---------- Helper: get best ask price for a token ID ----------
def get_best_ask(token_id):
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            book = resp.json()
            asks = book.get('asks', [])
            if asks:
                return float(asks[0][0])  # best ask price
    except:
        pass
    return None

# ---------- Recommendation ----------
def get_recommendation(interval='5m'):
    slug, market = get_market_slug(interval)
    if not market:
        return f"⚠️ Could not find BTC {interval} market. Try again later."

    # Extract token IDs
    token_ids = market.get('clob_token_ids')
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    if not token_ids or len(token_ids) < 2:
        return f"⚠️ No token IDs for {slug}"

    up_token = token_ids[0]
    down_token = token_ids[1]

    ask_up = get_best_ask(up_token)
    ask_down = get_best_ask(down_token)

    if ask_up is None or ask_down is None:
        return f"⚠️ Could not fetch order book for {slug}"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = market.get('title', f"BTC {interval} market")

    if ask_up < ask_down:
        rec = "BUY UP"
        edge = (ask_down - ask_up) / ask_up * 100
        msg = (
            f"📈 *{title}*\n"
            f"Slug: `{slug}`\n\n"
            f"UP ask (price to buy): ${ask_up:.3f}\n"
            f"DOWN ask (price to buy): ${ask_down:.3f}\n\n"
            f"🎯 *Recommendation*: {rec} (cheaper)\n"
            f"📊 Edge: {edge:.1f}%"
        )
    else:
        rec = "BUY DOWN"
        edge = (ask_up - ask_down) / ask_down * 100
        msg = (
            f"📈 *{title}*\n"
            f"Slug: `{slug}`\n\n"
            f"UP ask (price to buy): ${ask_up:.3f}\n"
            f"DOWN ask (price to buy): ${ask_down:.3f}\n\n"
            f"🎯 *Recommendation*: {rec} (cheaper)\n"
            f"📊 Edge: {edge:.1f}%"
        )
    return msg + f"\n\n(Data as of {timestamp})"

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I fetch real order book ask prices (what you actually pay) for BTC Up/Down markets.\n\n"
        "Commands:\n"
        "/signalbtc5m – 5‑minute market\n"
        "/signalbtc15m – 15‑minute market\n"
        "/ping – Alive check",
        parse_mode='Markdown'
    )

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_btc15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong!")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    app.add_handler(CommandHandler("signalbtc15m", signal_btc15m))
    print("Advisory bot started (order book based).")
    app.run_polling()

if __name__ == "__main__":
    main()
