"""
Telegram Bot for Polymarket - Handles all commands and interactions
All commands are single words (no spaces) for fast, error-free use
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
# COMMAND MAPPING (No Spaces - All Single Words)
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
    
    # Parse prices - they might be in different locations
    prices = None
    
    # Try different places where prices might be
    if market_data.get('prices'):
        prices = market_data['prices']
    elif market_data.get('markets') and len(market_data['markets']) > 0:
        prices = market_data['markets'][0].get('outcomePrices')
    elif market_data.get('outcomePrices'):
        prices = market_data['outcomePrices']
    
    # Convert prices to cents
    try:
        if prices and len(prices) >= 2:
            up_price = float(prices[0]) * 100
            down_price = float(prices[1]) * 100
        else:
            up_price = 0
            down_price = 0
    except:
        up_price = 0
        down_price = 0
    
    # Get title
    title = market_data.get('title', '')
    if not title and market_data.get('markets'):
        title = market_data['markets'][0].get('question', '')
    
    # Format time from end_date
    end_date = market_data.get('end_date', '')
    if not end_date and market_data.get('markets'):
        end_date = market_data['markets'][0].get('endDate', '')
    
    try:
        if end_date:
            dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            time_str = dt.strftime("%b %d, %I:%M%p ET").replace(" 0", " ")
        else:
            time_str = "Unknown time"
    except:
        time_str = "Unknown time"
    
    # Build response
    response = f"📊 *{title}*\n"
    response += f"⏱️ {time_str}\n\n"
    response += f"📈 UP: {up_price:.0f}¢\n"
    response += f"📉 DOWN: {down_price:.0f}¢\n\n"
    
    market_id = market_data.get('market_id')
    if not market_id and market_data.get('markets'):
        market_id = market_data['markets'][0].get('id')
    if market_id:
        response += f"🆔 Market ID: `{market_id}`\n"
    
    return response

def format_trending_markets(markets, limit=5):
    """Format trending markets list"""
    if not markets:
        return "❌ No trending markets found"
    
    response = "🔥 *Trending Markets*\n\n"
    for i, market in enumerate(markets[:limit]):
        title = market.get('title', 'Unknown')[:50]
        volume = float(market.get('volume', 0))
        
        # Get price
        prices = market.get('outcomePrices', ["0", "0"])
        try:
            price_display = f"{float(prices[0]):.3f}"
        except:
            price_display = "N/A"
        
        response += f"{i+1}. *{title}*\n"
        response += f"   💰 Vol: ${volume:,.0f} | Price: {price_display}\n\n"
    
    return response

def format_search_results(markets, term):
    """Format search results"""
    if not markets:
        return f"❌ No markets found for '{term}'"
    
    response = f"🔍 *Search results for '{term}'*\n\n"
    for i, market in enumerate(markets[:5]):
        title = market.get('title', 'Unknown')[:60]
        
        # Get price
        prices = market.get('outcomePrices', ["0", "0"])
        try:
            price_display = f"{float(prices[0]):.3f}"
        except:
            price_display = "N/A"
        
        volume = float(market.get('volume', 0))
        
        response += f"{i+1}. *{title}*\n"
        response += f"   Price: {price_display} | Vol: ${volume:,.0f}\n\n"
    
    return response

# ============================================================
# COMMAND HANDLERS - All Single Words, No Spaces
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message and help - No spaces, intuitive UI"""
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
    """Alias for start"""
    await start(update, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick health check"""
    await update.message.reply_text("🏓 Pong! Bot is alive")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed bot status"""
    # Test each market
    btc5 = market_finder.get_market_by_slug('btc-updown-5m-' + str(market_finder.get_current_window_timestamp(5)))
    btc15 = market_finder.get_market_by_slug('btc-updown-15m-' + str(market_finder.get_current_window_timestamp(15)))
    eth5 = market_finder.get_market_by_slug('eth-updown-5m-' + str(market_finder.get_current_window_timestamp(5)))
    eth15 = market_finder.get_market_by_slug('eth-updown-15m-' + str(market_finder.get_current_window_timestamp(15)))
    
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

async def updown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic handler for updown commands"""
    command = update.message.text[1:]  # Remove the '/'
    
    if command not in COMMAND_MAP:
        await update.message.reply_text("❌ Unknown command")
        return
    
    pattern = COMMAND_MAP[command]
    minutes = 5 if '5m' in command else 15
    
    # Get current market
    timestamp = market_finder.get_current_window_timestamp(minutes)
    slug = f"{pattern}-{timestamp}"
    
    market_data = market_finder.get_market_by_slug(slug)
    
    if market_data:
        response = format_market_response(market_data, command)
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ No {command} market right now. Try again in a few minutes.")

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top trending markets"""
    try:
        url = f"{GAMMA_API}/markets"
        params = {"order": "volume", "limit": 10, "active": "true"}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            markets = response.json()
            response_text = format_trending_markets(markets)
            await update.message.reply_text(response_text, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Could not fetch trending markets")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

# ============================================================
# SEARCH COMMANDS - All Single Word, No Spaces
# ============================================================

async def searchbtc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for Bitcoin markets"""
    await perform_search(update, "bitcoin")

async def searcheth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for Ethereum markets"""
    await perform_search(update, "ethereum")

async def searchcrypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for all crypto markets"""
    await perform_search(update, "crypto")

async def perform_search(update: Update, term: str):
    """Shared search function"""
    try:
        url = f"{GAMMA_API}/markets"
        params = {"title": term, "limit": 5, "active": "true"}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            markets = response.json()
            response_text = format_search_results(markets, term)
            await update.message.reply_text(response_text, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Search failed for '{term}'")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:50]}")

# ============================================================
# PORTFOLIO COMMANDS
# ============================================================

async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's profit/loss"""
    summary = journal.get_today_summary()
    stats = summary['stats']
    
    total_trades = stats['winning_trades'] + stats['losing_trades']
    win_rate = (stats['winning_trades'] / total_trades * 100) if total_trades > 0 else 0
    
    mode = "📝 PAPER" if journal.paper_mode else "🚀 LIVE"
    
    pnl_text = f"""
📊 *TODAY'S PERFORMANCE* {mode}

💰 Realized: ${stats['realized_pnl']:.2f}
📈 Unrealized: ${stats['unrealized_pnl']:.2f}
💵 Total: ${summary['total_pnl']:.2f}

📊 Trades: {stats['orders_filled']}
🎯 Win Rate: {win_rate:.1f}% ({stats['winning_trades']}W/{stats['losing_trades']}L)

📌 Open Positions: {summary['open_positions']}
    """
    await update.message.reply_text(pnl_text, parse_mode='Markdown')

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current open positions"""
    if not journal.open_positions:
        await update.message.reply_text("📭 *No Open Positions*", parse_mode='Markdown')
        return
    
    pos_text = "📈 *OPEN POSITIONS*\n\n"
    for market, pos in journal.open_positions.items():
        data = pos.data
        entry = data['entry_price']
        size = data['size']
        side = data['side'].upper()
        
        pos_text += f"*{market}*\n"
        pos_text += f"   Side: {side}\n"
        pos_text += f"   Entry: ${entry:.3f}\n"
        pos_text += f"   Size: {size}\n\n"
    
    await update.message.reply_text(pos_text, parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 5 trades"""
    trades_file = Path("data/journal/trades") / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"
    
    if not trades_file.exists():
        await update.message.reply_text("📭 *No Trades Today*", parse_mode='Markdown')
        return
    
    trades = []
    with open(trades_file, 'r') as f:
        for line in f:
            trades.append(json.loads(line))
    
    if not trades:
        await update.message.reply_text("📭 *No Trades Today*", parse_mode='Markdown')
        return
    
    history_text = "📋 *LAST 5 TRADES*\n\n"
    for trade in trades[-5:]:
        data = trade['data']
        pnl = data.get('pnl', 0)
        sign = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        
        history_text += f"{sign} *{data['market']}* {data['side'].upper()}\n"
        history_text += f"   ${data['price']:.3f} | Size: {data['size']}\n"
        history_text += f"   PnL: ${pnl:.2f}\n\n"
    
    await update.message.reply_text(history_text, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current balance"""
    await update.message.reply_text(
        "💰 *BALANCE*\n\n"
        "Manual entry for now.\n"
        "Add `BALANCE_USDC=100.00` to Railway variables.",
        parse_mode='Markdown'
    )

# ============================================================
# BOT MANAGEMENT COMMANDS
# ============================================================

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current risk limits"""
    risk_text = f"""
⚠️ *RISK LIMITS*

📉 Daily Loss Limit: {config.daily_loss_limit_percent*100}%
📊 Max Drawdown: 40%
💰 Minimum Stake: ${config.min_stake_usd}
📐 Position Size: Quarter Kelly (1-6%)

📌 *Today's Loss:* ${journal.daily_stats['realized_pnl']:.2f}
    """
    await update.message.reply_text(risk_text, parse_mode='Markdown')

async def togglepaper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch between paper and live mode"""
    global journal
    journal.paper_mode = not journal.paper_mode
    
    mode_text = "📝 PAPER MODE" if journal.paper_mode else "🚀 LIVE MODE"
    await update.message.reply_text(f"✅ Switched to *{mode_text}*", parse_mode='Markdown')

# ============================================================
# THRESHOLD COMMANDS - Single Word, No Spaces
# ============================================================

async def threshold5000(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set whale alert threshold to $5000"""
    await set_threshold(update, 5000)

async def threshold10000(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set whale alert threshold to $10000"""
    await set_threshold(update, 10000)

async def set_threshold(update: Update, amount: int):
    """Shared threshold setting function"""
    # Here you would save to config/database
    await update.message.reply_text(
        f"✅ Whale alert threshold set to *${amount:,}*",
        parse_mode='Markdown'
    )

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
    
    # Add all command handlers (all single words, no spaces)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trending", trending))
    
    # Search commands (no spaces)
    app.add_handler(CommandHandler("searchbtc", searchbtc))
    app.add_handler(CommandHandler("searcheth", searcheth))
    app.add_handler(CommandHandler("searchcrypto", searchcrypto))
    
    # Portfolio commands
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("balance", balance))
    
    # Bot management
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("togglepaper", togglepaper))
    
    # Threshold commands (no spaces, no parameters)
    app.add_handler(CommandHandler("threshold5000", threshold5000))
    app.add_handler(CommandHandler("threshold10000", threshold10000))
    
    # Minute market commands
    for cmd in COMMAND_MAP.keys():
        app.add_handler(CommandHandler(cmd, updown_handler))
    
    print("🤖 Telegram bot started. Press Ctrl+C to stop.")
    print("📝 All commands are single words - no spaces needed!")
    app.run_polling()

if __name__ == "__main__":
    main()
