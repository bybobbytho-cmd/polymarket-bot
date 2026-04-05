"""
Telegram Bot – Advisory with debug command to list signals.
"""

import os
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

# ---------- Helper: format signal with explicit market name ----------
def get_signal_message(asset='btc', interval='5m'):
    signal = trader.get_signal(asset, interval)
    if not signal:
        return f"⚠️ No market data for {asset.upper()} {interval}. The bot may still be initializing. Try again in a minute."

    # Market name for display
    if asset == 'btc':
        market_name = f"Bitcoin {interval} market"
    else:
        market_name = f"{asset.upper()} {interval} market"

    side = signal.get('side')
    if not side or not signal.get('actionable'):
        return (
            f"📉 *{market_name}* – No clear edge.\n"
            f"Market ask (YES): ${signal['ask_price']:.3f}\n"
            f"Fair value (external model): ${signal['fair_value']:.3f}\n"
            f"Edge: {signal['edge']*100:.1f}%\n"
            f"*Explanation:*\n"
            f"- CME futures change: {signal.get('futures_change', 0)*100:.1f}%\n"
            f"- Binance order book imbalance: {signal.get('binance_imbalance', 0):.2f}\n"
            f"- News sentiment: {signal.get('news_sentiment', 0):.2f}\n"
            f"Required edge > {trader.MIN_EDGE*100:.0f}% to trigger a BUY."
        )

    # Actionable signal
    msg = (
        f"🚀 *{market_name}* – BUY {side} at ask price or better!\n"
        f"Market ask (YES): ${signal['ask_price']:.3f}\n"
        f"Fair value: ${signal['fair_value']:.3f}\n"
        f"Edge: {signal['edge']*100:.1f}%\n"
        f"*Why?*\n"
        f"- CME futures change: {signal.get('futures_change', 0)*100:.1f}%\n"
        f"- Binance order book imbalance: {signal.get('binance_imbalance', 0):.2f}\n"
        f"- News sentiment: {signal.get('news_sentiment', 0):.2f}\n"
        f"Suggested stake: $1.00\n"
        f"Place a limit order now."
    )
    return msg

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Polymarket Advisory Bot*\n\n"
        "I analyze external data (CME futures, Binance order book, news) and send you trading signals automatically when there's an edge.\n\n"
        "*Commands:*\n"
        "/signalbtc5m – recommendation for Bitcoin 5‑minute market\n"
        "/signalbtc15m – recommendation for Bitcoin 15‑minute market\n"
        "/showsignals – list all stored signals (debug)\n"
        "/status – Bot health\n"
        "/strategy – Strategy parameters\n"
        "/pause – Pause signal generation\n"
        "/resume – Resume\n"
        "/ping – Alive check\n"
        "/help – This message",
        parse_mode='Markdown'
    )

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_signal_message('btc', '5m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_btc15m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_signal_message('btc', '15m')
    await update.message.reply_text(msg, parse_mode='Markdown')

async def show_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trader.signals:
        await update.message.reply_text("No signals stored yet. The bot may still be initializing. Wait a minute and try again.")
        return
    lines = []
    for slug, sig in trader.signals.items():
        lines.append(f"`{slug}`: edge={sig['edge']*100:.1f}%, actionable={sig['actionable']}")
    msg = "📡 *Stored signals:*\n" + "\n".join(lines[:10])  # limit to 10
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
    await update.message.reply_text(
        "📊 *Strategy Parameters*\n\n"
        "- External signals: CME futures (40%), Binance order book imbalance (40%), news sentiment (20%)\n"
        "- Fair value = weighted combination\n"
        "- Edge = (fair value - ask) / ask\n"
        f"- Min edge threshold: {trader.MIN_EDGE*100:.0f}% (adjustable in trader.py)\n"
        "- Signals sent automatically when edge > threshold",
        parse_mode='Markdown'
    )

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

# ---------- Background Jobs (no 15‑min report) ----------
async def trader_job(context: ContextTypes.DEFAULT_TYPE):
    trader.run_cycle()

async def auto_signal_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    for slug, signal in trader.signals.items():
        if signal.get('actionable'):
            last_sent = trader.last_sent_signal.get(slug, 0)
            if signal['timestamp'] > last_sent:
                trader.last_sent_signal[slug] = signal['timestamp']
                parts = slug.split('-')
                if len(parts) >= 3:
                    asset = parts[0]
                    interval = parts[2]
                    msg = get_signal_message(asset, interval)
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def start_with_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Remove existing jobs
    current_jobs = context.application.job_queue.jobs()
    for job in current_jobs:
        if job.name in [f"trader_{chat_id}", f"auto_signal_{chat_id}"]:
            job.schedule_removal()
    # Schedule trader job every 60 seconds
    context.application.job_queue.run_repeating(
        trader_job, interval=60, first=10,
        chat_id=chat_id, name=f"trader_{chat_id}"
    )
    # Schedule auto signal job every 60 seconds
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
    app.add_handler(CommandHandler("start", start_with_jobs))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("strategy", strategy))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("pause", pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    app.add_handler(CommandHandler("signalbtc15m", signal_btc15m))
    app.add_handler(CommandHandler("showsignals", show_signals))
    print("🤖 Advisory bot started. Commands: /signalbtc5m, /signalbtc15m, /showsignals")
    app.run_polling()

if __name__ == "__main__":
    main()
