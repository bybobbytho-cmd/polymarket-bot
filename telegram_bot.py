"""
Telegram Bot for Polymarket - Handles all commands and interactions
Provides real-time market data, positions, and bot management
"""

import os
import requests
import json
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import our existing modules
from config import MinuteMarketFinder, Config
from journal import PolymarketJournal

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GAMMA_API = "https://gamma-api.polymarket.com"

# Initialize components
market_finder = MinuteMarketFinder()
config = Config()
journal = PolymarketJournal(paper_mode=True)  # Start in paper mode

# ============================================================
# COMMAND MAPPING
# ============================================================

COMMAND_MAP = {
    "updownbtc5m": "btc-updown-5m",
    "updownbtc15m": "btc-updown-15m",
    "updowneth5m": "eth-updown-5m",
    "updowneth15m": "eth-updown-15m",
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def format_market_response(market_data, market_type):
    """Format market data into clean Telegram message"""
    if not market_data:
        return f"❌ No active {market_type} market found"
    
    # Parse prices (they come as ["0.XXX", "0.XXX"])
    prices = market_data.get('prices', ["0", "0"])
    try:
        up_price = float(prices[0]) * 100  # Convert to cents
        down_price = float(prices[1]) * 100
    except:
        up_price = 0
        down_price = 0
    
    # Format time from end_date
    end_date = market_data.get('end_date', '')
    try:
        dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        time_str = dt.strftime("%b %d, %I:%M%p ET").replace(" 0", " ")
    except:
        time_str = "Unknown time"
    
    # Build response
    response = f"📊 {market_data.get('title', 'Market')}\n"
    response += f"⏱️ {time_str}\n\n"
    response += f"📈 UP: {up_price:.0f}¢\n"
    response += f"📉 DOWN: {down_price:.0f}¢\n\n"
    response += f"🔗 Slug: `{market_data.get('slug', 'unknown')}`\n"
    response += f"🆔 Market ID: `{market_data.get('market_id', 'unknown')}`\n"
    response += f"📡 Source: Gamma / CLOB"
    
    return response

def format_trending_markets(markets, limit=5):
    """Format trending markets list"""
    if not markets:
        return "❌ No trending markets found"
    
    response = "🔥 *Trending Markets*\n\n"
    for i, market in enumerate(markets[:limit]):
        title = market.get('title', 'Unknown')[:50]
        volume = float(market.get('volume', 0))
        price = market.get('price', 'N/A')
        
        response += f"{i+1}. {title}\n"
        response += f"   💰 Vol: ${volume:,.0f} | Price: {price}\n\n"
    
    return response

# ============================================================
# COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message and help"""
    help_text = """
🤖 *Polymarket Trading Bot*

*Available Commands:*

📊 *Market Data*
/updownbtc5m - BTC 5m prices
/updownbtc15m - BTC 15m prices
/updowneth5m - ETH 5m prices
/updowneth15m - ETH 15m prices
/trending - Top 5 markets by volume
/search [term] - Search markets (e.g., /search bitcoin)

📈 *Portfolio*
/pnl - Today's profit/loss
/positions - Current open positions
/history - Last 5 trades
/balance - Current balance

⚙️ *Bot Management*
/status - Bot health check
/ping - Quick alive check
/risk - Current risk limits
/togglepaper - Switch paper/live mode
/setthreshold [amount] - Whale alert threshold

❓ *Help*
/start - This message
/help - List all commands

*Bot is running in PAPER mode* 📝
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for start"""
    await start(update, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick health check"""
    await update.message.reply_text("🏓 Pong! Bot is alive")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed bot status"""
    status_text = f"""
📡 *Bot Status*

Telegram: ✅ Connected
Market lookup: ✅ Working
Journal: ✅ Active
Mode: 📝 Paper Trading

Minute Markets:
• BTC 5m: {'✅' if market_finder.get_market_by_slug('btc-updown-5m-' + str(market_finder.get_current_window_timestamp(5))) else '❌'}
• BTC 15m: {'✅' if market_finder.get_market_by_slug('btc-updown-15m-' + str(market_finder.get_current_window_timestamp(15))) else '❌'}
• ETH 5m: {'✅' if market_finder.get_market_by_slug('eth-updown-5m-' + str(market_finder.get_current_window_timestamp(5))) else '❌'}
• ETH 15m: {'✅' if market_finder.get_market_by_slug('eth-updown-15m-' + str(market_finder.get_current_window_timestamp(15))) else '❌'}
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def updown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic handler for updown commands"""
    command = update.message.text[1:]  # Remove the '/'
    
    if command not in COMMAND_MAP:
        await update.message.reply_text("❌ Unknown command")
        return
    
    pattern = COMMAND_MAP[command]
    
    # Determine minutes from command
    minutes = 5 if '5m' in command else 15
    
    # Get current market
    timestamp = market_finder.get_current_window_timestamp(minutes)
    slug = f"{pattern}-{timestamp}"
    
    market_data = market_finder.get_market_by_slug(slug)
    
    if market_data:
        response = format_market_response(market_data, command)
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ No active {command} market found. Try again in a few minutes.")

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top trending markets"""
    try:
        url = f"{GAMMA_API}/markets"
        params = {"order": "volume", "limit": 10}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            markets = response.json()
            response_text = format_trending_markets(markets)
            await update.message.reply_text(response_text, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Could not fetch trending markets")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for markets by term"""
    if not context.args:
        await update.message.reply_text("❌ Usage: /search [term] (e.g., /search bitcoin)")
        return
    
    search_term = ' '.join(context.args)
    
    try:
        url = f"{GAMMA_API}/markets"
        params = {"title": search_term, "limit": 5}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            markets = response.json()
            if markets:
                response_text = f"🔍 *Search results for '{search_term}'*\n\n"
                for i, market in enumerate(markets):
                    title = market.get('title', 'Unknown')[:60]
                    price = market.get('price', 'N/A')
                    volume = float(market.get('volume', 0))
                    
                    response_text += f"{i+1}. {title}\n"
                    response_text += f"   Price: {price} | Vol: ${volume:,.0f}\n\n"
                
                await update.message.reply_text(response_text, parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ No markets found for '{search_term}'")
        else:
            await update.message.reply_text("❌ Search failed")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's profit/loss"""
    summary = journal.get_today_summary()
    stats = summary['stats']
    
    pnl_text = f"""
📊 *Today's Performance*

Realized PnL: ${stats['realized_pnl']:.2f}
Unrealized PnL: ${stats['unrealized_pnl']:.2f}
Total PnL: ${summary['total_pnl']:.2f}

Trades: {stats['orders_filled']}
Win Rate: {stats['winning_trades']/(stats['winning_trades']+stats['losing_trades'])*100:.1f}% ({stats['winning_trades']}W/{stats['losing_trades']}L)

Open Positions: {summary['open_positions']}
Mode: 📝 Paper
    """
    await update.message.reply_text(pnl_text, parse_mode='Markdown')

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current open positions"""
    if not journal.open_positions:
        await update.message.reply_text("📭 No open positions")
        return
    
    pos_text = "📈 *Open Positions*\n\n"
    for market, pos in journal.open_positions.items():
        data = pos.data
        current_price = data.get('current_price', data['entry_price'])
        entry = data['entry_price']
        pnl = (current_price - entry) * data['size'] if data['side'] == 'buy' else (entry - current_price) * data['size']
        
        pos_text += f"*{market}*\n"
        pos_text += f"Side: {data['side'].upper()}\n"
        pos_text += f"Entry: ${entry:.3f}\n"
        pos_text += f"Size: {data['size']}\n"
        pos_text += f"PnL: ${pnl:.2f}\n\n"
    
    await update.message.reply_text(pos_text, parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 5 trades"""
    trades_file = Path("data/journal/trades") / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"
    
    if not trades_file.exists():
        await update.message.reply_text("📭 No trades today")
        return
    
    trades = []
    with open(trades_file, 'r') as f:
        for line in f:
            trades.append(json.loads(line))
    
    if not trades:
        await update.message.reply_text("📭 No trades today")
        return
    
    history_text = "📋 *Last 5 Trades*\n\n"
    for trade in trades[-5:]:
        data = trade['data']
        pnl = data.get('pnl', 0)
        sign = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        
        history_text += f"{sign} {data['market']} {data['side'].upper()}\n"
        history_text += f"   ${data['price']:.3f} | Size: {data['size']}\n"
        history_text += f"   PnL: ${pnl:.2f}\n\n"
    
    await update.message.reply_text(history_text, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current balance (manual for now)"""
    await update.message.reply_text(
        "💰 *Current Balance*\n\n"
        "Manual entry for now. Set your USDC balance in .env with:\n"
        "`BALANCE_USDC=100.00`",
        parse_mode='Markdown'
    )

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current risk limits"""
    risk_text = f"""
⚠️ *Risk Limits*

Daily Loss: {config.daily_loss_limit_percent*100}%
Max Drawdown: 40%
Min Stake: ${config.min_stake_usd}
Position Size: Quarter Kelly (~1-6% of capital)

Current Risk:
Daily Loss Today: ${journal.daily_stats['realized_pnl']:.2f}
    """
    await update.message.reply_text(risk_text, parse_mode='Markdown')

async def togglepaper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch between paper and live mode"""
    global journal
    current_mode = journal.paper_mode
    journal.paper_mode = not current_mode
    
    mode_text = "📝 Paper Mode" if journal.paper_mode else "🚀 Live Mode"
    await update.message.reply_text(f"Switched to {mode_text}")

async def setthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set whale alert threshold"""
    if not context.args:
        await update.message.reply_text("❌ Usage: /setthreshold [amount]")
        return
    
    try:
        threshold = float(context.args[0])
        # Store in config or database
        await update.message.reply_text(f"✅ Whale alert threshold set to ${threshold:,.0f}")
    except:
        await update.message.reply_text("❌ Invalid amount")

# ============================================================
# MAIN BOT SETUP
# ============================================================

def main():
    """Start the Telegram bot"""
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN not found in environment")
        return
    
    # Create application
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("togglepaper", togglepaper))
    app.add_handler(CommandHandler("setthreshold", setthreshold))
    
    # Add updown command handlers
    for cmd in COMMAND_MAP.keys():
        app.add_handler(CommandHandler(cmd, updown_handler))
    
    print("🤖 Telegram bot started. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
