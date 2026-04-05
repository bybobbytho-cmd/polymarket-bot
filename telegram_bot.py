"""
Polymarket Advisory Bot – On‑demand signals, no paper trading.
"""

import os
import time
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

from orderbook import get_token_id_from_slug, get_order_book
from external_signals import ExternalSignals

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set")

# Global instance for external signals
ext = ExternalSignals()

# ---------- Helper: fetch market slug for BTC up/down by timeframe ----------
def get_btc_market_slug(interval='5m'):
    """Return the current active market slug for BTC up/down."""
    period = 300 if interval == '5m' else 900
    now = int(time.time())
    window_start = now - (now % period)
    slug = f"btc-updown-{interval}-{window_start}"
    # Verify market exists
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data and len(data) > 0:
            return slug
    except:
        pass
    return None

# ---------- Helper: get current ask price for YES token ----------
def get_yes_ask_price(slug):
    yes_token, _ = get_token_id_from_slug(slug)
    if not yes_token:
        return None
    book = get_order_book(yes_token)
    if not book or not book.get('asks'):
        return None
    return float(book['asks'][0][0])

# ---------- Helper: build recommendation message ----------
def get_recommendation(asset='btc', interval='5m'):
    slug = get_btc_market_slug(interval)
    if not slug:
        return f"⚠️ Could not find active {asset.upper()} {interval} market. Try again in a moment."

    ask_price = get_yes_ask_price(slug)
    if ask_price is None:
        return f"⚠️ No order book data for {asset.upper()} {interval}. Market may be inactive."

    # Fetch external signals
    futures_change = ext.get_cme_futures_change() or 0.0
    binance_imb = ext.get_binance_btc_orderbook_imbalance() or 0.0
    news_sent = ext.get_news_sentiment() or 0.0

    # Compute fair value (same weights as before)
    futures_score = max(0.0, min(1.0, 0.5 + 10 * futures_change))
    imbalance_score = (binance_imb + 1) / 2
    sentiment_score = (news_sent + 1) / 2
    fair_value = 0.4 * futures_score + 0.4 * imbalance_score + 0.2 * sentiment_score

    edge = (fair_value - ask_price) / ask_price if ask_price > 0 else 0
    min_edge = 0.01  # 1% threshold for "actionable"

    if edge > min_edge:
        recommendation = f"🚀 *BUY YES* at ask price or better!"
    else:
        recommendation = f"⏸️ *NO TRADE* – edge too small."

    msg = (
        f"📈 *{asset.upper()} {interval} market*\n"
        f"{recommendation}\n"
        f"Market ask (YES): ${ask_price:.3f}\n"
        f"Fair value: ${fair_value:.3f}\n"
        f"Edge: {edge*100:.1f}%\n"
        f"*Why?*\n"
        f"- CME futures change: {futures_change*100:.1f}%\n"
        f"- Binance order book imbalance: {binance_imb:.2f}\n"
        f"- News sentiment: {news_sent:.2f}\n"
    )
    return msg

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I analyze real‑time data (CME futures, Binance order book, news) and tell you whether to buy YES on BTC up/down markets.\n\n"
        "*Commands:*\n"
        "/signalbtc5m – recommendation for Bitcoin 5‑minute market\n"
        "/signalbtc15m – recommendation for Bitcoin 15‑minute market\n"
        "/status – Health of data sources\n"
        "/ping – Alive check\n"
        "/help – This message",
        parse_mode='Markdown'
    )

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('btc', '5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_btc15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('btc', '15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check external data sources
    futures = ext.get_cme_futures_change()
    binance = ext.get_binance_btc_orderbook_imbalance()
    news = ext.get_news_sentiment()
    status_msg = (
        "📡 *Data Source Health*\n"
        f"- CME Futures: {'✅' if futures is not None else '❌'}\n"
        f"- Binance Order Book: {'✅' if binance is not None else '❌'}\n"
        f"- News Sentiment: {'✅' if news is not None else '❌'} (using neutral default if unavailable)\n\n"
        "Bot is ready. Use /signalbtc5m or /signalbtc15m for trading advice."
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    app.add_handler(CommandHandler("signalbtc15m", signal_btc15m))
    print("🤖 Advisory bot started. Use /signalbtc5m or /signalbtc15m")
    app.run_polling()

if __name__ == "__main__":
    main()
