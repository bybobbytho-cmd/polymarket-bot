"""
Telegram Bot – Advisory with manual /signal command and automatic alerts.
"""

import os
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
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

# ---------- Helper to format signal message ----------
def format_signal(signal, market_name):
    if not signal or not signal.get('actionable'):
        return f"🔍 *{market_name}*: No clear edge right now."
    side = signal['side']
    ask = signal['ask_price']
    fair = signal['fair_value']
    edge = signal['edge'] * 100
    if side == 'YES':
        recommendation = "✅ *BUY YES* at ask price or better"
    else:
        recommendation = "✅ *BUY NO* at ask price or better"
    return (
        f"📈 *{market_name}*\n"
        f"{recommendation}\n"
        f"Market Price (Ask): ${ask:.3f}\n"
        f"Fair Value: ${fair:.3f}\n"
        f"Edge: {edge:.1f}%\n"
        f"Suggested Stake: $1.00"
    )

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I analyze external data (CME futures, Binance order book, news) and send you trading signals automatically when there's an edge.\n\n"
        "You can also manually check any market:\n"
        "`/signal btc 5m` – get recommendation for Bitcoin 5‑minute market\n"
        "`/signal btc 15m` – for 15‑minute market\n\n"
        f"Virtual capital: ${trader.capital:.2f}\n\n"
        "*Other commands:*\n"
        "/status – Bot health\n"
        "/strategy – Strategy parameters\n"
        "/pause – Pause signal generation\n"
        "/resume – Resume\n"
        "/ping – Alive check\n"
        "/help – This message"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual signal check: /signal btc 5m"""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /signal <asset> <interval>\nExample: /signal btc 5m")
        return
    asset = context.args[0].lower()
    interval = context.args[1].lower()
    if asset not in ['btc'] or interval not in ['5m', '15m']:
        await update.message.reply_text("Only 'btc' with '5m' or '15m' supported for now.")
        return
    signal = trader.get_signal(asset, interval)
    market_name = f"{asset.upper()} {interval}"
    msg = format_signal(signal, market_name)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = trader.get_status()
    cap = summary['capital']
    peak = summary['peak_capital']
    drawdown = (1 - cap/peak)*100 if peak>0 else 0
    stats = summary['journal_summary'].get('stats', {})
    realized = stats.get('realized_pnl', 0.0)
    trades = stats.get('orders_filled', 0)
    wins = stats.get('winning_trades', 0)
    losses = stats.get('losing_trades', 0)
    win_rate = wins / max(1, wins+losses) * 100
    msg = f"""
📊 *BOT STATUS*
Capital: ${cap:.2f} | Peak: ${peak:.2f} | Drawdown: {drawdown:.1f}%
Status: {'⏸️ PAUSED' if summary['paused'] else '▶️ ACTIVE'}

📈 Today (paper):
Realized PnL: ${realized:.2f}
Trades: {trades} | Win Rate: {win_rate:.1f}%
Consecutive losses: {summary['consecutive_losses']}
    """
    await update.message.reply_text(msg, parse_mode='Markdown')

async def strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📊 *Strategy Parameters*\n\n"
        "- External signals: CME futures (40%), Binance order book imbalance (40%), news sentiment (20%)\n"
        "- Fair value = weighted combination\n"
        "- Edge = (fair value - ask) / ask\n"
        "- Min edge threshold: 2% (adjustable in trader.py)\n"
        "- Signals sent automatically when edge > 2%"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.pause()
    await update.message.reply_text("⏸️ Signal generation paused.")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trader.resume()
    await update.message.reply_text("▶️ Signal generation resumed.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! Bot is alive.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ---------- Background Jobs ----------
async def send_periodic_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    status_data = trader.get_status()
    cap = status_data['capital']
    peak = status_data['peak_capital']
    drawdown = (1 - cap/peak)*100 if peak>0 else 0
    stats = status_data['journal_summary'].get('stats', {})
    realized = stats.get('realized_pnl', 0.0)
    trades = stats.get('orders_filled', 0)
    wins = stats.get('winning_trades', 0)
    losses = stats.get('losing_trades', 0)
    win_rate = wins / max(1, wins+losses) * 100
    msg = f"""
📊 *15‑MINUTE REPORT*
Capital: ${cap:.2f} | Peak: ${peak:.2f} | Drawdown: {drawdown:.1f}%
Status: {'⏸️ PAUSED' if status_data['paused'] else '▶️ ACTIVE'}

Today:
Realized PnL: ${realized:.2f}
Trades: {trades} | Win Rate: {win_rate:.1f}%
Consecutive losses: {status_data['consecutive_losses']}
    """
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def trader_job(context: ContextTypes.DEFAULT_TYPE):
    trader.run_cycle()

async def auto_signal_job(context: ContextTypes.DEFAULT_TYPE):
    """Send automatic alert for any market that has an actionable signal."""
    chat_id = context.job.chat_id
    for slug, signal in trader.signals.items():
        if signal.get('actionable'):
            # Avoid duplicate alerts for the same market
            last_sent = trader.last_sent_signal.get(slug, 0)
            if signal['timestamp'] > last_sent:
                trader.last_sent_signal[slug] = signal['timestamp']
                # Extract market name from slug (e.g., btc-updown-5m-123456)
                parts = slug.split('-')
                if len(parts) >= 3:
                    market_name = f"{parts[0].upper()} {parts[2]}"
                else:
                    market_name = slug
                msg = format_signal(signal, market_name)
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def start_with_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Remove existing jobs
    current_jobs = context.application.job_queue.jobs()
    for job in current_jobs:
        if job.name in [f"report_{chat_id}", f"trader_{chat_id}", f"auto_signal_{chat_id}"]:
            job.schedule_removal()
    # Schedule jobs
    context.application.job_queue.run_repeating(
        send_periodic_report, interval=900, first=60,
        chat_id=chat_id, name=f"report_{chat_id}"
    )
    context.application.job_queue.run_repeating(
        trader_job, interval=60, first=10,
        chat_id=chat_id, name=f"trader_{chat_id}"
    )
    context.application.job_queue.run_repeating(
        auto_signal_job, interval=60, first=5,
        chat_id=chat_id, name=f"auto_signal_{chat_id}"
    )
    await start(update, context)

# ---------- Main ----------
def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN not found")
        return
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_with_report))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("strategy", strategy))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("pause", pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("signal", signal_command))
    print("🤖 Advisory bot started. Use /signal btc 5m or wait for automatic alerts.")
    app.run_polling()

if __name__ == "__main__":
    main()
