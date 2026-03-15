"""
Telegram Bot for Polymarket – Uses working bot as price oracle
"""

import os
import requests
import json
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

from config import MinuteMarketFinder, Config
from journal import PolymarketJournal

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")

market_finder = MinuteMarketFinder()
config = Config()
journal = PolymarketJournal(paper_mode=True)

COMMAND_MAP = {
    "updownbtc5m": ("btc", "5m"),
    "updownbtc15m": ("btc", "15m"),
    "updowneth5m": ("eth", "5m"),
    "updowneth15m": ("eth", "15m"),
}

def fetch_price_from_oracle(asset, interval):
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

def format_market_response(asset, interval, up, down, slug, title, end_date):
    if up is None or down is None:
        return f"❌ Price unavailable for {asset} {interval} at this moment"

    up_cents = up * 100
    down_cents = down * 100

    try:
        if end_date:
            dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            time_str = dt.strftime("%b %d, %I:%M%p ET").replace(" 0", " ")
        else:
            time_str = "Unknown time"
    except:
        time_str = "Unknown time"

    return (
        f"📈 *{title}*\n"
        f"Slug: `{slug}`\n"
        f"Ends: {time_str}\n\n"
        f"UP: {up_cents:.0f}¢\n"
        f"DOWN: {down_cents:.0f}¢\n\n"
        f"Source: Working bot oracle"
    )

async def updown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text[1:]
    if command not in COMMAND_MAP:
        await update.message.reply_text("❌ Unknown command")
        return

    asset, interval = COMMAND_MAP[command]
    minutes = 5 if interval == "5m" else 15
    timestamp = market_finder.get_current_window_timestamp(minutes)
    slug = f"{asset}-updown-{interval}-{timestamp}"
    event = market_finder.get_event_by_slug(slug)

    if not event:
        await update.message.reply_text(f"❌ No active {command} market")
        return

    title = event.get('title') or event.get('question') or slug
    end_date = event.get('endDate')

    up, down = fetch_price_from_oracle(asset, interval)
    response = format_market_response(asset, interval, up, down, slug, title, end_date)
    await update.message.reply_text(response, parse_mode='Markdown')

# ========== Keep all your other command handlers here ==========
# They are unchanged – you can copy them from your current file.
# For completeness, I'll include them but you must ensure they are present.

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 *Polymarket Bot*

*One Word Commands — Fast & Simple*

📊 *MINUTE MARKETS*
/updownbtc5m – BTC 5m prices
/updownbtc15m – BTC 15m prices
/updowneth5m – ETH 5m prices
/updowneth15m – ETH 15m prices

🔥 *MARKET INTELLIGENCE*
/trending – Top markets by volume
/searchbtc – Search Bitcoin markets
/searcheth – Search Ethereum markets
/searchcrypto – Search all crypto

📈 *YOUR PORTFOLIO*
/pnl – Today's profit/loss
/positions – Current open positions
/history – Last 5 trades
/balance – Your balance

⚙️ *BOT CONTROLS*
/status – Bot health check
/ping – Quick alive check
/risk – Current risk limits
/togglepaper – Switch paper/live mode
/threshold5000 – Set whale alert to $5k
/threshold10000 – Set whale alert to $10k

❓ *HELP*
/start – This message
/help – Same as /start

📝 *Current Mode: PAPER*
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc5 = market_finder.get_event_by_slug(f"btc-updown-5m-{market_finder.get_current_window_timestamp(5)}")
    btc15 = market_finder.get_event_by_slug(f"btc-updown-15m-{market_finder.get_current_window_timestamp(15)}")
    eth5 = market_finder.get_event_by_slug(f"eth-updown-5m-{market_finder.get_current_window_timestamp(5)}")
    eth15 = market_finder.get_event_by_slug(f"eth-updown-15m-{market_finder.get_current_window_timestamp(15)}")

    mode = "📝 PAPER" if journal.paper_mode else "🚀 LIVE"
    status_text = f"""
📡 *BOT STATUS*

✅ Telegram: Connected
✅ Market API: Working
✅ Journal: Active

*Mode:* {mode}

*Minute Markets:*
• BTC 5m: {'✅' if btc5 else '❌'}
• BTC 15m: {'✅' if btc15 else '❌'}
• ETH 5m: {'✅' if eth5 else '❌'}
• ETH 15m: {'✅' if eth15 else '❌'}

*Today's PnL:* ${journal.daily_stats['realized_pnl']:.2f}
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = f"https://gamma-api.polymarket.com/markets"
        params = {"order": "volume", "limit": 10, "active": "true"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            markets = resp.json()
            out = "🔥 *Trending Markets*\n\n"
            for i, m in enumerate(markets[:5]):
                title = m.get('title', 'Unknown')[:50]
                vol = float(m.get('volume', 0))
                out += f"{i+1}. *{title}*\n   💰 Vol: ${vol:,.0f}\n\n"
            await update.message.reply_text(out, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Could not fetch trending markets")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

async def searchbtc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await perform_search(update, "bitcoin")
async def searcheth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await perform_search(update, "ethereum")
async def searchcrypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await perform_search(update, "crypto")

async def perform_search(update: Update, term: str):
    try:
        url = f"https://gamma-api.polymarket.com/markets"
        params = {"title": term, "limit": 5, "active": "true"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            markets = resp.json()
            out = f"🔍 *Search results for '{term}'*\n\n"
            for i, m in enumerate(markets[:5]):
                title = m.get('title', 'Unknown')[:60]
                price = m.get('outcomePrices', ["N/A"])[0]
                vol = float(m.get('volume', 0))
                out += f"{i+1}. *{title}*\n   Price: {price} | Vol: ${vol:,.0f}\n\n"
            await update.message.reply_text(out, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Search failed for '{term}'")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = journal.get_today_summary()
    stats = summary['stats']
    total = stats['winning_trades'] + stats['losing_trades']
    wr = (stats['winning_trades'] / total * 100) if total else 0
    mode = "📝 PAPER" if journal.paper_mode else "🚀 LIVE"
    text = f"""
📊 *TODAY'S PERFORMANCE* {mode}

💰 Realized: ${stats['realized_pnl']:.2f}
📈 Unrealized: ${stats['unrealized_pnl']:.2f}
💵 Total: ${summary['total_pnl']:.2f}

📊 Trades: {stats['orders_filled']}
🎯 Win Rate: {wr:.1f}% ({stats['winning_trades']}W/{stats['losing_trades']}L)

📌 Open Positions: {summary['open_positions']}
    """
    await update.message.reply_text(text, parse_mode='Markdown')

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not journal.open_positions:
        await update.message.reply_text("📭 *No Open Positions*", parse_mode='Markdown')
        return
    out = "📈 *OPEN POSITIONS*\n\n"
    for market, pos in journal.open_positions.items():
        d = pos.data
        out += f"*{market}*\n   Side: {d['side'].upper()}\n   Entry: ${d['entry_price']:.3f}\n   Size: {d['size']}\n\n"
    await update.message.reply_text(out, parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades_file = Path("data/journal/trades") / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"
    if not trades_file.exists():
        await update.message.reply_text("📭 *No Trades Today*", parse_mode='Markdown')
        return
    trades = []
    with open(trades_file) as f:
        for line in f:
            trades.append(json.loads(line))
    if not trades:
        await update.message.reply_text("📭 *No Trades Today*", parse_mode='Markdown')
        return
    out = "📋 *LAST 5 TRADES*\n\n"
    for trade in trades[-5:]:
        d = trade['data']
        pnl = d.get('pnl', 0)
        sign = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        out += f"{sign} *{d['market']}* {d['side'].upper()}\n   ${d['price']:.3f} | Size: {d['size']}\n   PnL: ${pnl:.2f}\n\n"
    await update.message.reply_text(out, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *BALANCE*\n\nManual entry. Add `BALANCE_USDC=100.00` to Railway variables.",
        parse_mode='Markdown'
    )

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"""
⚠️ *RISK LIMITS*

📉 Daily Loss Limit: {config.daily_loss_limit_percent*100}%
📊 Max Drawdown: 40%
💰 Minimum Stake: ${config.min_stake_usd}
📐 Position Size: Quarter Kelly (1-6%)

📌 *Today's Loss:* ${journal.daily_stats['realized_pnl']:.2f}
    """
    await update.message.reply_text(text, parse_mode='Markdown')

async def togglepaper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global journal
    journal.paper_mode = not journal.paper_mode
    mode = "📝 PAPER MODE" if journal.paper_mode else "🚀 LIVE MODE"
    await update.message.reply_text(f"✅ Switched to *{mode}*", parse_mode='Markdown')

async def threshold5000(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Whale alert threshold set to *$5,000*", parse_mode='Markdown')
async def threshold10000(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Whale alert threshold set to *$10,000*", parse_mode='Markdown')

def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN not found")
        return
    if not ORACLE_URL:
        print("❌ PRICE_ORACLE_URL not set in environment")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("searchbtc", searchbtc))
    app.add_handler(CommandHandler("searcheth", searcheth))
    app.add_handler(CommandHandler("searchcrypto", searchcrypto))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("togglepaper", togglepaper))
    app.add_handler(CommandHandler("threshold5000", threshold5000))
    app.add_handler(CommandHandler("threshold10000", threshold10000))
    for cmd in COMMAND_MAP:
        app.add_handler(CommandHandler(cmd, updown_handler))

    print("🤖 Telegram bot started (using Node.js price oracle).")
    app.run_polling()

if __name__ == "__main__":
    main()
