"""
Polymarket Advisory Bot – Uses bestAsk/bestBid from market data.
"""

import os
import time
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set")

def get_market_data(interval='5m'):
    period = 300 if interval == '5m' else 900
    now = int(time.time())
    window_start = now - (now % period)
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0]
    except:
        pass
    # Fallback to previous window
    window_start -= period
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0]
    except:
        pass
    return None

def get_recommendation(interval='5m'):
    market = get_market_data(interval)
    if not market:
        return f"⚠️ Could not find BTC {interval} market. Try again later."

    # Extract the tradable prices
    best_ask = market.get('bestAsk')      # price to buy UP
    best_bid = market.get('bestBid')      # price to sell UP
    if best_ask is None or best_bid is None:
        return f"⚠️ No bid/ask data for BTC {interval} market."

    # Approximate price to buy DOWN as 1 - best_bid (since UP + DOWN ≈ 1)
    ask_down = 1 - best_bid

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = market.get('title', f"BTC {interval} market")
    slug = market.get('slug')

    if best_ask < ask_down:
        rec = "BUY UP"
        edge = (ask_down - best_ask) / best_ask * 100
        msg = (
            f"📈 *{title}*\n"
            f"Slug: `{slug}`\n\n"
            f"Price to buy UP: ${best_ask:.3f}\n"
            f"Price to buy DOWN (approx): ${ask_down:.3f}\n\n"
            f"🎯 *Recommendation*: {rec} (cheaper)\n"
            f"📊 Edge: {edge:.1f}%"
        )
    else:
        rec = "BUY DOWN"
        edge = (best_ask - ask_down) / ask_down * 100
        msg = (
            f"📈 *{title}*\n"
            f"Slug: `{slug}`\n\n"
            f"Price to buy UP: ${best_ask:.3f}\n"
            f"Price to buy DOWN (approx): ${ask_down:.3f}\n\n"
            f"🎯 *Recommendation*: {rec} (cheaper)\n"
            f"📊 Edge: {edge:.1f}%"
        )
    return msg + f"\n\n(Data as of {timestamp})"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I fetch real-time bid/ask prices for BTC Up/Down markets and recommend the cheaper side.\n\n"
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
    print("Advisory bot started (using bestAsk/bestBid).")
    app.run_polling()

if __name__ == "__main__":
    main()
