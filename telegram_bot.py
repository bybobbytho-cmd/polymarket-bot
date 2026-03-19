"""
Telegram Bot for Polymarket – with pause/resume, periodic reports, and kill switch.
Fixed chat_id and KeyError issues.
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

async def start_trader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.run_cycle()
    await update.message.reply_text("Trader cycle executed. Check journal for any paper trades.")

async def export_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    journal.export_to_csv()
    today = datetime.now().strftime('%Y%m%d')
    csv_file = Path("data/journal/summaries") / f"trades_{today}.csv"
    if csv_file.exists():
        with open(csv_file, 'rb') as f:
            await update.message.reply_document(f, filename=f"trades_{today}.csv", caption="Today's paper trades.")
    else:
        await update.message.reply_text("No trades file found for today.")

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

async def strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📊 *Current Strategy*\n\n"
        "Simple mean‑reversion on BTC 5m & 15m:\n"
        f"- Entry threshold: {trader.ENTRY_THRESHOLD}\n"
        f"- Take profit: {trader.TAKE_PROFIT_PCT*100}%\n"
        f"- Stop loss: {trader.STOP_LOSS_PCT*100}%\n"
        f"- Consecutive loss limit: {trader.CONSECUTIVE_LOSS_LIMIT}\n"
        f"- Daily loss limit: ${trader.DAILY_LOSS_LIMIT:.2f}\n"
        f"Virtual capital: ${trader.capital:.2f}\n"
        f"Status: {'PAUSED' if trader.paused else 'ACTIVE'}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.paused = True
    await update.message.reply_text("⏸️ Bot paused. No new trades will be entered.")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.paused = False
    trader.consecutive_losses = 0  # reset when resuming
    await update.message.reply_text("▶️ Bot resumed. New trades may be entered.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = journal.get_today_summary()
    stats = summary.get('stats', {})
    total_trades = stats.get('winning_trades', 0) + stats.get('losing_trades', 0)
    win_rate = (stats.get('winning_trades', 0) / total_trades * 100) if total_trades > 0 else 0
    realized = stats.get('realized_pnl', 0.0)
    unrealized = summary.get('unrealized_pnl', 0.0)  # safe default
    total = realized + unrealized
    drawdown = (1 - trader.capital / trader.peak_capital) * 100 if trader.peak_capital > 0 else 0
    msg = f"""
📊 *BOT STATUS*
Virtual capital: ${trader.capital:.2f}
Peak capital: ${trader.peak_capital:.2f}
Drawdown: {drawdown:.1f}%
Status: {'⏸️ PAUSED' if trader.paused else '▶️ ACTIVE'}

📈 Today:
Realized PnL: ${realized:.2f}
Unrealized PnL: ${unrealized:.2f}
Total PnL: ${total:.2f}
Trades: {stats.get('orders_filled', 0)}
Win rate: {win_rate:.1f}% ({stats.get('winning_trades', 0)}W/{stats.get('losing_trades', 0)}L)
Consecutive losses: {trader.consecutive_losses}
    """
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Polymarket Bot*\n\n"
        f"Virtual capital: ${trader.capital:.2f}\n\n"
        "Commands:\n"
        "/updownbtc5m – BTC 5m prices\n"
        "/updownbtc15m – BTC 15m prices\n"
        "/updowneth5m – ETH 5m prices\n"
        "/updowneth15m – ETH 15m prices\n"
        "/trending – Top markets by volume\n"
        "/searchbtc – Search Bitcoin markets\n"
        "/searcheth – Search Ethereum markets\n"
        "/searchcrypto – Search all crypto\n"
        "/pnl – Today's performance\n"
        "/trades – List today's paper trades\n"
        "/positions – Current open positions\n"
        "/history – Last 5 trades\n"
        "/balance – Your virtual balance\n"
        "/status – Bot health and stats\n"
        "/strategy – Show current parameters\n"
        "/pause – Pause new trades\n"
        "/resume – Resume trading\n"
        "/testprice btc 5m – Raw oracle output\n"
        "/start_trader – Run one trader cycle\n"
        "/export – Download today's trade CSV\n"
        "/help – This message"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await status(update, context)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💰 *VIRTUAL BALANCE*\n\nCurrent capital: ${trader.capital:.2f}", parse_mode='Markdown')

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trader.positions:
        await update.message.reply_text("📭 *No Open Positions*", parse_mode='Markdown')
        return
    out = "📈 *OPEN POSITIONS*\n\n"
    for slug, pos in trader.positions.items():
        out += f"*{slug}*\n   Side: {pos['side'].upper()}\n   Entry: ${pos['entry_price']:.3f}\n   Stake: ${pos['size']:.2f}\n\n"
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
        stake = d['size']
        pnl = d.get('pnl', 0.0)
        sign = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        out += f"{sign} *{d['market']}* {d['side'].upper()}\n   ${d['price']:.3f} | Stake ${stake:.2f} | PnL ${pnl:.2f}\n\n"
    await update.message.reply_text(out, parse_mode='Markdown')

# ---------- Background jobs ----------
async def send_periodic_report(context: ContextTypes.DEFAULT_TYPE):
    """Send a summary every 15 minutes."""
    chat_id = context.job.chat_id
    summary = journal.get_today_summary()
    stats = summary.get('stats', {})
    total_trades = stats.get('winning_trades', 0) + stats.get('losing_trades', 0)
    win_rate = (stats.get('winning_trades', 0) / total_trades * 100) if total_trades > 0 else 0
    realized = stats.get('realized_pnl', 0.0)
    unrealized = summary.get('unrealized_pnl', 0.0)
    total = realized + unrealized
    drawdown = (1 - trader.capital / trader.peak_capital) * 100 if trader.peak_capital > 0 else 0
    msg = f"""
📊 *15‑MINUTE REPORT*
Capital: ${trader.capital:.2f} | Peak: ${trader.peak_capital:.2f} | Drawdown: {drawdown:.1f}%
Status: {'⏸️ PAUSED' if trader.paused else '▶️ ACTIVE'}

Today:
Realized: ${realized:.2f} | Unrealized: ${unrealized:.2f} | Total: ${total:.2f}
Trades: {stats.get('orders_filled', 0)} | Win Rate: {win_rate:.1f}%
Consecutive losses: {trader.consecutive_losses}
    """
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def trader_job(context: ContextTypes.DEFAULT_TYPE):
    """Run one trader cycle and check for critical alerts."""
    trader.run_cycle()
    # Check if auto‑paused and send alert
    if trader.paused:
        # Determine why paused
        if trader.consecutive_losses >= 3:
            alert = f"⏸️ Bot paused due to {trader.consecutive_losses} consecutive losses."
        elif journal.daily_stats['realized_pnl'] <= -trader.DAILY_LOSS_LIMIT:
            alert = f"⏸️ Bot paused because daily loss limit (${trader.DAILY_LOSS_LIMIT:.2f}) was reached."
        else:
            alert = "⏸️ Bot paused (manual or other reason)."
        # Only send if we have a chat_id
        if context.job.chat_id:
            await context.bot.send_message(chat_id=context.job.chat_id, text=alert)

async def start_with_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command that also schedules periodic jobs."""
    chat_id = update.effective_chat.id
    # Remove any existing jobs for this chat
    current_jobs = context.application.job_queue.jobs()
    for job in current_jobs:
        if job.name == f"report_{chat_id}" or job.name == f"trader_{chat_id}":
            job.schedule_removal()
    # Schedule periodic report every 15 minutes
    context.application.job_queue.run_repeating(
        send_periodic_report, interval=900, first=60, 
        chat_id=chat_id, name=f"report_{chat_id}"
    )
    # Schedule trader job every 60 seconds
    context.application.job_queue.run_repeating(
        trader_job, interval=60, first=10, 
        chat_id=chat_id, name=f"trader_{chat_id}"
    )
    await start(update, context)

def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN not found")
        return
    if not ORACLE_URL:
        print("❌ PRICE_ORACLE_URL not set in environment")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_with_report))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("strategy", strategy))
    app.add_handler(CommandHandler("ping", lambda u,c: u.message.reply_text("🏓 Pong!")))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("pause", pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("trending", lambda u,c: u.message.reply_text("Trending not implemented yet")))
    app.add_handler(CommandHandler("searchbtc", lambda u,c: u.message.reply_text("Search not implemented yet")))
    app.add_handler(CommandHandler("searcheth", lambda u,c: u.message.reply_text("Search not implemented yet")))
    app.add_handler(CommandHandler("searchcrypto", lambda u,c: u.message.reply_text("Search not implemented yet")))
    app.add_handler(CommandHandler("testprice", testprice))
    app.add_handler(CommandHandler("start_trader", start_trader))
    app.add_handler(CommandHandler("export", export_journal))
    app.add_handler(CommandHandler("trades", list_trades))
    for cmd, (asset, interval) in COMMAND_MAP.items():
        app.add_handler(CommandHandler(cmd, updown_handler))

    print("🤖 Telegram bot started with pause/resume and periodic reports.")
    app.run_polling()

if __name__ == "__main__":
    main()
