"""
Polymarket Maker Bot – Places limit orders at best bid/ask, earns rebates.
Paper trading simulation with rebate tracking.
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

# ---------- Configuration ----------
CAPITAL = 10.0          # starting paper capital
REBATE_PCT = 0.002      # 0.2% maker rebate (adjust based on market)
MIN_SPREAD = 0.01       # minimum spread (1%) to consider placing orders
POSITION_SIZE = 0.50    # each trade uses $0.50

# Global state for paper maker
maker_positions = []    # list of open limit orders
maker_pnl = 0.0
maker_rebates = 0.0
maker_trades = 0

# ---------- Helper: get current market data (slug, best bid/ask) ----------
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
                market = data[0]
                best_bid = market.get('bestBid')
                best_ask = market.get('bestAsk')
                if best_bid is not None and best_ask is not None:
                    return slug, float(best_bid), float(best_ask), market
    except:
        pass
    # fallback to previous window
    window_start -= period
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                market = data[0]
                best_bid = market.get('bestBid')
                best_ask = market.get('bestAsk')
                if best_bid is not None and best_ask is not None:
                    return slug, float(best_bid), float(best_ask), market
    except:
        pass
    return None, None, None, None

# ---------- Simulate placing a limit order (bid or ask) ----------
def place_limit_order(side, price, size=POSITION_SIZE):
    global maker_positions, maker_pnl, maker_rebates, maker_trades
    maker_positions.append({
        'side': side,
        'price': price,
        'size': size,
        'timestamp': time.time(),
        'filled': False
    })
    # Record the trade (paper)
    maker_trades += 1
    # Rebate will be added when order is taken (simulated later)
    return f"📝 Placed LIMIT {side} order at ${price:.3f} for ${size:.2f}"

# ---------- Simulate checking if limit orders are taken ----------
def check_fills(current_bid, current_ask):
    global maker_positions, maker_pnl, maker_rebates, CAPITAL
    new_positions = []
    for order in maker_positions:
        if order['filled']:
            new_positions.append(order)
            continue
        filled = False
        if order['side'] == 'BUY' and current_ask <= order['price']:
            filled = True
            # Buyer took our bid? Actually, if we placed a BUY limit at bid, it gets taken when ask drops to our price.
            # Simplified: if best ask <= our buy price, our order is taken.
            profit = 0  # we'll calculate when we sell
            maker_pnl += profit
            maker_rebates += order['size'] * REBATE_PCT
            CAPITAL -= order['size'] * order['price']  # spend capital
        elif order['side'] == 'SELL' and current_bid >= order['price']:
            filled = True
            profit = order['size'] * (order['price'] - order['price'])  # placeholder
            maker_pnl += profit
            maker_rebates += order['size'] * REBATE_PCT
            CAPITAL += order['size'] * order['price']
        if not filled:
            new_positions.append(order)
    maker_positions = new_positions

# ---------- Recommendation: suggest a maker order ----------
def get_maker_recommendation(interval='5m'):
    slug, bid, ask, market = get_market_data(interval)
    if bid is None or ask is None:
        return f"⚠️ Could not fetch market data for BTC {interval}."
    spread_pct = (ask - bid) / bid * 100
    title = market.get('title', f"BTC {interval} market")

    # Simple logic: if spread > MIN_SPREAD, place a limit order at the best bid (to buy) or best ask (to sell)
    # We'll recommend buying at bid (maker) because it adds liquidity.
    recommendation = (
        f"📈 *{title}*\n"
        f"Slug: `{slug}`\n"
        f"Best Bid: ${bid:.3f} | Best Ask: ${ask:.3f}\n"
        f"Spread: {spread_pct:.2f}%\n\n"
        f"🎯 *Maker Action*: Place a **LIMIT BUY** order at ${bid:.3f} (best bid)\n"
        f"   → Adds liquidity, earns ~{REBATE_PCT*100:.1f}% rebate when filled.\n"
        f"Suggested size: ${POSITION_SIZE:.2f}\n\n"
        f"To simulate, use /buylimit {bid} or /selllimit {ask}"
    )
    return recommendation

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Maker Bot*\n\n"
        "I recommend limit orders at best bid/ask to earn rebates.\n\n"
        "Commands:\n"
        "/maker5m – recommendation for 5‑minute market\n"
        "/maker15m – recommendation for 15‑minute market\n"
        "/buylimit <price> – simulate placing a BUY limit order\n"
        "/selllimit <price> – simulate placing a SELL limit order\n"
        "/status – show paper PnL, rebates, open orders\n"
        "/ping – alive check",
        parse_mode='Markdown'
    )

async def maker5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_maker_recommendation('5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def maker15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_maker_recommendation('15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def buylimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /buylimit <price>")
        return
    try:
        price = float(context.args[0])
        msg = place_limit_order('BUY', price)
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("Invalid price")

async def selllimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /selllimit <price>")
        return
    try:
        price = float(context.args[0])
        msg = place_limit_order('SELL', price)
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("Invalid price")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CAPITAL, maker_pnl, maker_rebates, maker_trades
    # Check fills based on current market prices
    slug, bid, ask, _ = get_market_data('5m')
    if bid and ask:
        check_fills(bid, ask)
    msg = (
        f"📊 *Paper Maker Status*\n"
        f"Capital: ${CAPITAL:.2f}\n"
        f"Realized PnL: ${maker_pnl:.2f}\n"
        f"Maker Rebates: ${maker_rebates:.2f}\n"
        f"Total Trades: {maker_trades}\n"
        f"Open Orders: {len(maker_positions)}\n"
        f"Current BTC 5m Bid: ${bid:.3f} | Ask: ${ask:.3f}" if bid else "Market data unavailable"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong!")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("maker5m", maker5m))
    app.add_handler(CommandHandler("maker15m", maker15m))
    app.add_handler(CommandHandler("buylimit", buylimit))
    app.add_handler(CommandHandler("selllimit", selllimit))
    app.add_handler(CommandHandler("status", status))
    print("Maker bot started – recommends limit orders to earn rebates.")
    app.run_polling()

if __name__ == "__main__":
    main()
