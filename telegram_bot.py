"""
Telegram Bot for Polymarket – Uses working bot as price oracle with candidate windows
Includes paper trading on BTC 5m & 15m, real‑time PnL, and auto‑close expired positions.
"""

import os
import requests
import json
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
from dotenv import load_dotenv

from config import MinuteMarketFinder, Config
from journal import PolymarketJournal
from trader import PaperTrader

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")
CAPITAL = float(os.getenv("BALANCE_USDC", "10.0"))

market_finder = MinuteMarketFinder()
config = Config()
journal = PolymarketJournal(paper_mode=True)
trader = PaperTrader(journal, market_finder, ORACLE_URL, CAPITAL)

COMMAND_MAP = {
    "updownbtc5m": ("btc", "5m"),
    "updownbtc15m": ("btc", "15m"),
    "updowneth5m": ("eth", "5m"),
    "updowneth15m": ("eth", "15m"),
}

def fetch_price_from_oracle(asset, interval):
    if not ORACLE_URL:
        print("❌ PRICE_ORACLE_URL not set")
        return None, None, None
    try:
        url = f"{ORACLE_URL}/api/price/{asset}/{interval}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('up'), data.get('down'), data
    except Exception as e:
        print(f"Oracle error: {e}")
    return None, None, None

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

    up, down, oracle_data = fetch_price_from_oracle(asset, interval)
    if oracle_data is None:
        await update.message.reply_text("❌ Oracle not reachable")
        return

    slug = oracle_data.get('slug')
    if not slug:
        await update.message.reply_text("❌ Oracle returned no slug")
        return

    market_data = market_finder.get_market_by_slug(slug)
    if not market_data:
        for start in market_finder.candidate_window_starts(minutes):
            alt_slug = f"{asset}-updown-{interval}-{start}"
            if alt_slug == slug:
                continue
            market_data = market_finder.get_market_by_slug(alt_slug)
            if market_data:
                slug = alt_slug
                break

    if not market_data:
        await update.message.reply_text(f"❌ Could not find market data for {slug}")
        return

    title = market_data.get('title') or market_data.get('question') or slug
    end_date = market_data.get('end_date')
    response = format_market_response(asset, interval, up, down, slug, title, end_date)
    await update.message.reply_text(response, parse_mode='Markdown')

# ========== STRATEGY EXPLANATION ==========
async def strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stake = max(1.0, CAPITAL * 0.02)
    msg = (
        "📊 *Current Strategy*\n\n"
        "Simple mean‑reversion on **BTC 5‑minute and 15‑minute** markets:\n"
        "- Buy YES when price < 0.20 (20¢)\n"
        "- Buy NO when price > 0.80 (80¢)\n"
        f"- Stake per trade: ${stake:.2f} (minimum $1, 2% of virtual capital)\n"
        "- Positions auto‑close after market end time (zero PnL if outcome unknown)\n\n"
        f"Virtual capital: ${CAPITAL:.2f}\n"
        "Paper mode only. Use `/togglepaper` to switch to live."
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ========== DIAGNOSTIC COMMAND ==========
async def testprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /testprice <asset> <interval> (e.g., /testprice btc 5m)")
        return
    try:
        asset = context.args[0].lower()
        interval = context.args[1].lower()
        up, down, raw = fetch_price_from_oracle(asset, interval)
        if raw:
            await update.message.reply_text(f"Raw oracle response:\n```json\n{json.dumps(raw, indent=2)}\n```", parse_mode='Markdown')
        else:
            await update.message.reply_text("Oracle returned no data.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# ========== TRADER CONTROL COMMANDS ==========
async def start_trader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.run_cycle()
    await update.message.reply_text("Trader cycle executed. Check journal for any paper trades.")

# ========== EXPORT JOURNAL COMMAND ==========
async def export_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    journal.export_to_csv()
    today = datetime.now().strftime('%Y%m%d')
    csv_file = Path("data/journal/summaries") / f"trades_{today}.csv"
    if csv_file.exists():
        with open(csv_file, 'rb') as f:
            await update.message.reply_document(f, filename=f"trades_{today}.csv", caption="Today's paper trades.")
    else:
        await update.message.reply_text("No trades file found for today.")

# ========== TRADES LIST COMMAND ==========
async def list_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades_file = Path("data/journal/trades") / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"
    if not trades_file.exists():
        await update.message.reply_text("📭 No trades today.")
        return

    trades = []
    with open(trades_file, 'r') as f:
        for line in f:
            trades.append(json.loads(line))

    if not trades:
        await update.message.reply_text("📭 No trades today.")
        return

    recent = trades[-10:]
    lines = []
    for t in recent:
        data = t['data']
        timestamp = t['timestamp'] if 'timestamp' in t else data.get('entry_time', 'unknown')
        side = data['side'].upper()
        market = data['market']
        price = data['price']
        stake = data['size']
        lines.append(f"🕒 {timestamp}\n{market}\n{side} @ ${price:.3f} | stake ${stake:.2f}")

    msg = "📋 *Last 10 paper trades*\n\n" + "\n\n".join(lines)
    await update.message.reply_text(msg, parse_mode='Markdown')

# ========== SIMPLIFIED START COMMAND ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 Polymarket Bot is running.\n\n"
        f"Virtual capital: ${CAPITAL:.2f}\n\n"
        "Commands:\n"
        "/updownbtc5m – BTC 5m prices\n"
        "/updownbtc15m – BTC 15m prices\n"
        "/updowneth5m – ETH 5m prices\n"
        "/updowneth15m – ETH 15m prices\n"
        "/trending – Top markets by volume\n"
        "/searchbtc – Search Bitcoin markets\n"
        "/searcheth – Search Ethereum markets\n"
        "/searchcrypto – Search all crypto\n"
        "/pnl – Today's performance (real-time)\n"
        "/trades – List today's paper trades\n"
        "/positions – Current open positions\n"
        "/history – Last 5 trades\n"
        "/balance – Your virtual balance\n"
        "/status – Bot health check\n"
        "/ping – Quick alive check\n"
        "/risk – Current risk limits\n"
        "/togglepaper – Switch paper/live mode\n"
        "/threshold5000 – Set whale alert to $5k\n"
        "/threshold10000 – Set whale alert to $10k\n"
        "/testprice btc 5m – Raw oracle output\n"
        "/start_trader – Run one trader cycle\n"
        "/export – Download today's trade CSV\n"
        "/strategy – Explain current strategy\n"
        "/help – This message"
    )
    await update.message.reply_text(help_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ========== PNL COMMAND (REAL-TIME) ==========
def parse_slug(slug):
    parts = slug.split('-')
    if len(parts) >= 4:
        asset = parts[0]
        interval = parts[2]
        return asset, interval
    return None, None

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_unrealized = 0.0
    for slug, pos in list(journal.open_positions.items()):
        asset, interval = parse_slug(slug)
        if asset and interval:
            up, down, _ = fetch_price_from_oracle(asset, interval)
            if up is not None and down is not None:
                current_price = up if pos.data['side'] == 'YES' else down
                pos.data['current_price'] = current_price
                if pos.data['side'] == 'YES':
                    pos.data['unrealized_pnl'] = (current_price - pos.data['entry_price']) * pos.data['size']
                else:
                    pos.data['unrealized_pnl'] = (pos.data['entry_price'] - current_price) * pos.data['size']
                total_unrealized += pos.data['unrealized_pnl']

    summary = journal.get_today_summary()
    stats = summary['stats']
    total_trades = stats['winning_trades'] + stats['losing_trades']
    win_rate = (stats['winning_trades'] / total_trades * 100) if total_trades > 0 else 0
    mode = "📝 PAPER" if journal.paper_mode else "🚀 LIVE"

    realized = stats['realized_pnl']
    unrealized = total_unrealized
    total = realized + unrealized
    total_stakes = stats['total_volume']

    text = f"""
📊 *TODAY'S PERFORMANCE* {mode}
Virtual Capital: ${CAPITAL:.2f}

💰 Realized PnL: ${realized:.2f} (trades closed)
📈 Unrealized PnL: ${unrealized:.2f} (open positions)
💵 Total PnL: ${total:.2f}

📊 Trades entered: {stats['orders_filled']}
💸 Total stakes: ${total_stakes:.2f}
🎯 Win Rate (closed): {win_rate:.1f}% ({stats['winning_trades']}W/{stats['losing_trades']}L)

📌 Open Positions: {summary['open_positions']}

*Note: Unrealized PnL updated in real-time from oracle.*
    """
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== BALANCE COMMAND ==========
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💰 *VIRTUAL BALANCE*\n\nCurrent capital: ${CAPITAL:.2f}\n"
        "Set `BALANCE_USDC` in Railway variables to change.",
        parse_mode='Markdown'
    )

# ========== STATUS COMMAND ==========
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc5 = market_finder.get_market_by_slug(f"btc-updown-5m-{market_finder.get_current_window_timestamp(5)}")
    btc15 = market_finder.get_market_by_slug(f"btc-updown-15m-{market_finder.get_current_window_timestamp(15)}")
    eth5 = market_finder.get_market_by_slug(f"eth-updown-5m-{market_finder.get_current_window_timestamp(5)}")
    eth15 = market_finder.get_market_by_slug(f"eth-updown-15m-{market_finder.get_current_window_timestamp(15)}")

    mode = "📝 PAPER" if journal.paper_mode else "🚀 LIVE"
    status_text = f"""
📡 *BOT STATUS*

✅ Telegram: Connected
✅ Market API: Working
✅ Journal: Active

*Mode:* {mode}
*Virtual Capital:* ${CAPITAL:.2f}

*Minute Markets:*
• BTC 5m: {'✅' if btc5 else '❌'}
• BTC 15m: {'✅' if btc15 else '❌'}
• ETH 5m: {'✅' if eth5 else '❌'}
• ETH 15m: {'✅' if eth15 else '❌'}

*Today's Total Stakes:* ${journal.daily_stats['total_volume']:.2f}
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ========== POSITIONS COMMAND ==========
async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not journal.open_positions:
        await update.message.reply_text("📭 *No Open Positions*", parse_mode='Markdown')
        return
    out = "📈 *OPEN POSITIONS*\n\n"
    for market, pos in journal.open_positions.items():
        d = pos.data
        current = d.get('current_price', 'N/A')
        if isinstance(current, float):
            current_str = f"${current:.3f}"
        else:
            current_str = current
        out += f"*{market}*\n   Side: {d['side'].upper()}\n   Entry: ${d['entry_price']:.3f}\n   Stake: ${d['size']:.2f}\n   Current: {current_str}\n\n"
    await update.message.reply_text(out, parse_mode='Markdown')

# ========== HISTORY COMMAND ==========
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
        stake = d['size']
        pnl = d.get('pnl', 0.0)
        sign = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        out += f"{sign} *{d['market']}* {d['side'].upper()}\n   ${d['price']:.3f} | Stake ${stake:.2f} | PnL ${pnl:.2f}\n\n"
    await update.message.reply_text(out, parse_mode='Markdown')

# ========== TRENDING, SEARCH, ETC ==========
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

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive")

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"""
⚠️ *RISK LIMITS*

📉 Daily Loss Limit: {config.daily_loss_limit_percent*100}%
📊 Max Drawdown: 40%
💰 Minimum Stake: ${config.min_stake_usd}
📐 Position Size: max($1, 2% of capital)

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

# ========== BACKGROUND TRADER JOB ==========
async def run_trader_job(context: ContextTypes.DEFAULT_TYPE):
    trader.run_cycle()

def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN not found")
        return
    if not ORACLE_URL:
        print("❌ PRICE_ORACLE_URL not set in environment")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    job_queue = app.job_queue

    # Schedule trader job every 60 seconds
    job_queue.run_repeating(run_trader_job, interval=60, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("strategy", strategy))
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
    app.add_handler(CommandHandler("testprice", testprice))
    app.add_handler(CommandHandler("start_trader", start_trader))
    app.add_handler(CommandHandler("export", export_journal))
    app.add_handler(CommandHandler("trades", list_trades))
    for cmd in COMMAND_MAP:
        app.add_handler(CommandHandler(cmd, updown_handler))

    print("🤖 Telegram bot started with paper trading job (every 60s) on BTC 5m & 15m.")
    app.run_polling()

if __name__ == "__main__":
    main()
