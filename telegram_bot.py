"""
Polymarket Advisory Bot – Debug version with oracle connectivity test.
"""

import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set")
if not ORACLE_URL:
    print("⚠️ PRICE_ORACLE_URL not set. Bot will not work.")

def get_oracle_price(asset='btc', interval='5m'):
    """Fetch up/down prices from your oracle."""
    if not ORACLE_URL:
        return None, None
    try:
        url = f"{ORACLE_URL}/api/price/{asset}/{interval}"
        print(f"Fetching: {url}")
        resp = requests.get(url, timeout=10)  # increased timeout
        print(f"Response status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            return data.get('up'), data.get('down')
        else:
            print(f"Oracle returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"Oracle error: {e}")
    return None, None

def get_recommendation(interval='5m'):
    up, down = get_oracle_price('btc', interval)
    if up is None or down is None:
        return f"⚠️ Could not fetch prices for BTC {interval}. Check /testoracle."

    THRESHOLD = 0.20
    if up < THRESHOLD:
        side = "YES"
        market_price = up
        fair_value = THRESHOLD + 0.05
    elif down < THRESHOLD:
        side = "NO"
        market_price = down
        fair_value = THRESHOLD + 0.05
    else:
        return (
            f"📉 *BTC {interval} market*\n"
            f"⏸️ *NO TRADE*\n"
            f"Up price: ${up:.3f}\n"
            f"Down price: ${down:.3f}\n"
            f"Threshold: ${THRESHOLD:.2f}"
        )

    edge = (fair_value - market_price) / market_price if market_price > 0 else 0
    msg = (
        f"📈 *BTC {interval} market*\n"
        f"🚀 *BUY {side}* at market price or better!\n"
        f"Current {side} price: ${market_price:.3f}\n"
        f"Fair value estimate: ${fair_value:.3f}\n"
        f"Edge: {edge*100:.1f}%\n"
        f"Place a limit order."
    )
    return msg

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I use your price oracle to recommend trades.\n\n"
        "*Commands:*\n"
        "/signalbtc5m – recommendation for 5‑minute market\n"
        "/signalbtc15m – recommendation for 15‑minute market\n"
        "/testoracle – test connection to your oracle\n"
        "/status – Check oracle health\n"
        "/ping – Alive check",
        parse_mode='Markdown'
    )

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_btc15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def test_oracle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test direct connection to the oracle."""
    if not ORACLE_URL:
        await update.message.reply_text("❌ PRICE_ORACLE_URL not set in environment.")
        return
    url = f"{ORACLE_URL}/api/price/btc/5m"
    try:
        resp = requests.get(url, timeout=10)
        await update.message.reply_text(f"✅ Oracle responded with status {resp.status_code}\n{resp.text[:300]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error connecting to oracle: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up5, down5 = get_oracle_price('btc', '5m')
    up15, down15 = get_oracle_price('btc', '15m')
    status_msg = (
        "📡 *Oracle Health*\n"
        f"BTC 5m – up: {up5}, down: {down5}\n"
        f"BTC 15m – up: {up15}, down: {down15}\n\n"
        "Use /testoracle for more details."
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("testoracle", test_oracle))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    app.add_handler(CommandHandler("signalbtc15m", signal_btc15m))
    print("🤖 Advisory bot started. Oracle URL:", ORACLE_URL)
    app.run_polling()

if __name__ == "__main__":
    main()
