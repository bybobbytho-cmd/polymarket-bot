"""
Polymarket Advisory Bot – Uses your price oracle for real‑time signals.
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
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('up'), data.get('down')
    except Exception as e:
        print(f"Oracle error: {e}")
    return None, None

def get_recommendation(interval='5m'):
    up, down = get_oracle_price('btc', interval)
    if up is None or down is None:
        return f"⚠️ Could not fetch prices for BTC {interval}. Oracle may be down."

    # Simple strategy: buy YES if up < 0.20, buy NO if down < 0.20
    # You can adjust the threshold or add more logic.
    THRESHOLD = 0.20
    if up < THRESHOLD:
        side = "YES"
        market_price = up
        fair_value = THRESHOLD + 0.05  # example fair value
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
            f"Threshold: ${THRESHOLD:.2f}\n"
            f"No side is below threshold."
        )

    edge = (fair_value - market_price) / market_price if market_price > 0 else 0
    msg = (
        f"📈 *BTC {interval} market*\n"
        f"🚀 *BUY {side}* at market price or better!\n"
        f"Current {side} price: ${market_price:.3f}\n"
        f"Fair value estimate: ${fair_value:.3f}\n"
        f"Edge: {edge*100:.1f}%\n"
        f"Suggested stake: $1.00\n"
        f"Place a limit order."
    )
    return msg

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I use your price oracle to recommend trades on BTC up/down markets.\n\n"
        "*Commands:*\n"
        "/signalbtc5m – recommendation for 5‑minute market\n"
        "/signalbtc15m – recommendation for 15‑minute market\n"
        "/status – Check oracle health\n"
        "/ping – Alive check\n"
        "/help – This message",
        parse_mode='Markdown'
    )

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_btc15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_recommendation('15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up5, down5 = get_oracle_price('btc', '5m')
    up15, down15 = get_oracle_price('btc', '15m')
    status_msg = (
        "📡 *Oracle Health*\n"
        f"BTC 5m – up: {up5}, down: {down5}\n"
        f"BTC 15m – up: {up15}, down: {down15}\n\n"
        "Bot is ready. Use /signalbtc5m or /signalbtc15m."
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
    print("🤖 Advisory bot started. Using oracle at:", ORACLE_URL)
    app.run_polling()

if __name__ == "__main__":
    main()
