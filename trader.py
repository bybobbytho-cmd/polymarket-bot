"""
Polymarket Trading Bot with Regime Detection
13 Commands: /start, /stop, /pause, /resume, /close, /status, /check, /btc5m, /time, /stats, /report, /export, /help
"""

import time
import csv
import os
import threading
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import get_live_price_from_oracle, Config
from market_data import get_market_snapshot
from regime import detect_regime
from executor import should_execute
from journal import PolymarketJournal

# ==================== CONFIGURABLE PARAMETERS ====================
POSITION_SIZE_USD = 1.0
MAX_POSITIONS = 3
MIN_CONFIDENCE = 70
TRADE_INTERVAL_SECONDS = 30
REPORT_FILE = "trade_reports.csv"
RESOLVED_FILE = "resolved_trades.csv"

# TIME WINDOW SETTINGS (seconds remaining in 5-minute market)
PRIME_WINDOW_START = 150
PRIME_WINDOW_END = 210
LATE_WINDOW_START = 90
LATE_WINDOW_END = 150
# ================================================================

# Global state
trading_active = True
trading_paused = False
trader_instance = None

def init_report_files():
    if not os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "slug", "time_remaining_sec", "regime", "confidence", "verdict",
                "direction", "outcome", "price", "size_usd", "shares",
                "obi", "velocity", "cme_basis", "polymarket_up", 
                "polymarket_down", "distance_to_strike", "reason"
            ])
    
    if not os.path.exists(RESOLVED_FILE):
        with open(RESOLVED_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "entry_timestamp", "exit_timestamp", "slug", "direction", 
                "outcome", "entry_price", "exit_price", "size_usd", 
                "shares", "pnl_usd", "pnl_percent", "result", "regime",
                "entry_time_remaining", "entry_obi", "entry_velocity", 
                "entry_cme_basis", "entry_distance"
            ])

def log_trade_decision(data):
    with open(REPORT_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data.get('timestamp'), data.get('slug'), data.get('time_remaining'),
            data.get('regime'), data.get('confidence'), data.get('verdict'),
            data.get('direction'), data.get('outcome'), data.get('price'),
            data.get('size_usd'), data.get('shares'), data.get('obi'),
            data.get('velocity'), data.get('cme_basis'), data.get('polymarket_up'),
            data.get('polymarket_down'), data.get('distance_to_strike'), data.get('reason')
        ])

def log_resolved_trade(entry, exit_price, pnl_usd, pnl_percent, result):
    with open(RESOLVED_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            entry['entry_time'], datetime.now(timezone.utc).isoformat(), entry['slug'],
            entry['direction'], entry['outcome'], entry['entry_price'], exit_price,
            entry['size_usd'], entry['shares'], pnl_usd, pnl_percent, result,
            entry['regime'], entry.get('entry_time_remaining'),
            entry.get('entry_obi'), entry.get('entry_velocity'),
            entry.get('entry_cme_basis'), entry.get('entry_distance')
        ])


class RegimeTrader:
    def __init__(self):
        self.positions = {}
        self.total_trades = 0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.last_report_hour = datetime.now(timezone.utc).hour
        
        self.regime_stats = {
            'WHALE_REGIME': {'wins': 0, 'losses': 0, 'trades': 0},
            'GRAVITY_REGIME': {'wins': 0, 'losses': 0, 'trades': 0},
            'RSI_EXTREME': {'wins': 0, 'losses': 0, 'trades': 0},
            'DEAD_ZONE': {'wins': 0, 'losses': 0, 'trades': 0},
            'CHAOS_REGIME': {'wins': 0, 'losses': 0, 'trades': 0}
        }
    
    def get_time_remaining(self, slug):
        try:
            timestamp = int(slug.split('-')[-1])
            window_end = timestamp + 300
            now = int(datetime.now(timezone.utc).timestamp())
            remaining = window_end - now
            return max(0, remaining)
        except:
            return 300
    
    def get_size_multiplier(self, time_remaining):
        if PRIME_WINDOW_START <= time_remaining <= PRIME_WINDOW_END:
            return 1.0
        elif LATE_WINDOW_START <= time_remaining < PRIME_WINDOW_START:
            return 0.5
        else:
            return 0
    
    def get_current_market_data(self):
        up, down, slug = get_live_price_from_oracle('btc', '5m')
        if not up:
            return None
        
        time_remaining = self.get_time_remaining(slug)
        snapshot = get_market_snapshot()
        strike = snapshot['spot_price'] - 50 if snapshot['spot_price'] else 75000
        distance = snapshot['spot_price'] - strike if snapshot['spot_price'] else 0
        
        return {
            'slug': slug,
            'time_remaining': time_remaining,
            'polymarket_up': up,
            'polymarket_down': down,
            'spot_price': snapshot['spot_price'],
            'obi': snapshot['obi'],
            'velocity': snapshot['velocity'],
            'cme_basis': snapshot['cme_basis'],
            'distance_to_strike': distance,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    def analyze_market(self, market_data):
        distance = abs(market_data['distance_to_strike'])
        time_remaining = market_data['time_remaining']
        
        size_mult = self.get_size_multiplier(time_remaining)
        if size_mult == 0:
            return {'execute': False, 'reason': f"Time window: {time_remaining}s remaining", 'regime': 'TIME_WINDOW', 'confidence': 0}
        
        regime, trade_dir, confidence, regime_reason = detect_regime(
            obi=market_data['obi'], cme_delta=market_data['cme_basis'],
            distance_to_strike=distance, velocity=market_data['velocity'], rsi_1h=50
        )
        
        execute, direction, _, exec_reason = should_execute(
            regime=regime, trade_direction=trade_dir,
            price_position=market_data['distance_to_strike'], distance_to_strike=distance, confidence=confidence
        )
        
        can_trade = trading_active and not trading_paused
        
        if execute and direction and confidence >= MIN_CONFIDENCE and can_trade:
            size_usd = POSITION_SIZE_USD * size_mult
            buy_price = market_data['polymarket_up'] if direction == "UP" else market_data['polymarket_down']
            outcome = "YES" if direction == "UP" else "NO"
            shares = size_usd / buy_price if buy_price > 0 else 0
            
            return {
                'execute': True, 'direction': direction, 'outcome': outcome,
                'price': buy_price, 'size_usd': size_usd, 'shares': shares,
                'confidence': confidence, 'regime': regime,
                'reason': f"{regime_reason} | {exec_reason}"
            }
        
        return {'execute': False, 'reason': f"{regime_reason} | {exec_reason}", 'regime': regime, 'confidence': confidence}

    def execute_trade(self, analysis, market_data):
        if not analysis['execute'] or market_data['slug'] in self.positions or len(self.positions) >= MAX_POSITIONS:
            return None
        
        position = {
            'slug': market_data['slug'], 'direction': analysis['direction'],
            'outcome': analysis['outcome'], 'entry_price': analysis['price'],
            'shares': analysis['shares'], 'size_usd': analysis['size_usd'],
            'entry_time': datetime.now(timezone.utc).isoformat(),
            'entry_time_remaining': market_data['time_remaining'], 'regime': analysis['regime'],
            'confidence': analysis['confidence'], 'entry_obi': market_data['obi'],
            'entry_velocity': market_data['velocity'], 'entry_cme_basis': market_data['cme_basis'],
            'entry_distance': market_data['distance_to_strike']
        }
        
        self.positions[market_data['slug']] = position
        self.total_trades += 1
        
        log_data = {
            'timestamp': market_data['timestamp'], 'slug': market_data['slug'],
            'time_remaining': market_data['time_remaining'], 'regime': analysis['regime'],
            'confidence': analysis['confidence'], 'verdict': 'EXECUTE',
            'direction': analysis['direction'], 'outcome': analysis['outcome'], 'price': analysis['price'],
            'size_usd': analysis['size_usd'], 'shares': analysis['shares'],
            'obi': market_data['obi'], 'velocity': market_data['velocity'],
            'cme_basis': market_data['cme_basis'], 'polymarket_up': market_data['polymarket_up'],
            'polymarket_down': market_data['polymarket_down'], 'distance_to_strike': market_data['distance_to_strike'],
            'reason': analysis['reason']
        }
        log_trade_decision(log_data)
        return position

    def close_all_positions(self):
        """Close all positions immediately (for /close command)"""
        for slug, pos in list(self.positions.items()):
            del self.positions[slug]
        return len(self.positions)

    def run_cycle(self):
        if not trading_active or trading_paused:
            return
        
        market_data = self.get_current_market_data()
        if not market_data:
            return
        
        analysis = self.analyze_market(market_data)
        
        if analysis['execute']:
            self.execute_trade(analysis, market_data)

    def send_hourly_report(self, send_func):
        current_hour = datetime.now(timezone.utc).hour
        if current_hour != self.last_report_hour:
            self.last_report_hour = current_hour
            
            report = f"""
📊 HOURLY REPORT ({current_hour-1}:00 - {current_hour}:00 UTC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Trades: {self.total_trades} | Wins: {self.wins} | Losses: {self.losses}
Win Rate: {(self.wins/self.total_trades*100) if self.total_trades > 0 else 0:.1f}%
PnL: ${self.total_pnl:.2f} | Active: {len(self.positions)}

📈 REGIME BREAKDOWN:
"""
            for regime, stats in self.regime_stats.items():
                if stats['trades'] > 0:
                    wr = stats['wins'] / stats['trades'] * 100
                    report += f"{regime}: {stats['wins']}W/{stats['losses']}L ({wr:.0f}%)\n"
            
            send_func(report)

    # ========== TELEGRAM COMMAND HANDLERS ==========
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        global trading_active, trading_paused
        trading_active = True
        trading_paused = False
        await update.message.reply_text("✅ Trading started! Use /stop to stop, /pause to pause, /check for market data.")

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        global trading_active
        trading_active = False
        await update.message.reply_text("⏹️ Trading stopped. Use /start to begin again.")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        global trading_paused
        trading_paused = True
        await update.message.reply_text("⏸️ Trading paused (positions held). Use /resume to continue.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        global trading_paused
        trading_paused = False
        trading_active = True
        await update.message.reply_text("▶️ Trading resumed.")

    async def cmd_close(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        count = self.close_all_positions()
        await update.message.reply_text(f"🔒 Closed {count} positions. They will resolve at market expiration.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        active = ""
        for slug, pos in self.positions.items():
            active += f"\n• {pos['direction']} @ ${pos['entry_price']:.3f} (${pos['size_usd']:.2f})"
        
        msg = f"""
🤖 BOT STATUS
━━━━━━━━━━━━━━━━━━━━━━━
Trading Active: {'✅' if trading_active else '❌'} | Paused: {'✅' if trading_paused else '❌'}
Total Trades: {self.total_trades}
Wins: {self.wins} | Losses: {self.losses}
Win Rate: {(self.wins/self.total_trades*100) if self.total_trades > 0 else 0:.1f}%
Total PnL: ${self.total_pnl:.2f}
Active Positions:{active or ' None'}
━━━━━━━━━━━━━━━━━━━━━━━
Size: ${POSITION_SIZE_USD} | Max: {MAX_POSITIONS} | Min Conf: {MIN_CONFIDENCE}%
Trade Window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining
        """
        await update.message.reply_text(msg)

    async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        market_data = self.get_current_market_data()
        if not market_data:
            await update.message.reply_text("❌ Cannot fetch market data")
            return
        
        time_remaining = market_data['time_remaining']
        minutes = time_remaining // 60
        seconds = time_remaining % 60
        
        regime, trade_dir, confidence, reason = detect_regime(
            obi=market_data['obi'], cme_delta=market_data['cme_basis'],
            distance_to_strike=abs(market_data['distance_to_strike']),
            velocity=market_data['velocity'], rsi_1h=50
        )
        
        msg = f"""
🔍 MARKET CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 POLYMARKET:
   UP: {market_data['polymarket_up']:.3f} | DOWN: {market_data['polymarket_down']:.3f}

⏰ TIME: {minutes}m {seconds}s remaining

📈 DATA:
   OBI: {market_data['obi']:.4f}
   Velocity: {market_data['velocity']:.1f} USD/min
   CME Basis: ${market_data['cme_basis']:.2f}

🎯 REGIME: {regime} ({confidence}%)
   {reason}

💡 Bot would {'EXECUTE ' + trade_dir if trade_dir != 'NONE' else 'PASS'}
        """
        await update.message.reply_text(msg)

    async def cmd_btc5m(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        up, down, slug = get_live_price_from_oracle('btc', '5m')
        if not up:
            await update.message.reply_text("❌ Oracle not responding")
            return
        
        time_remaining = self.get_time_remaining(slug)
        minutes = time_remaining // 60
        seconds = time_remaining % 60
        snapshot = get_market_snapshot()
        
        msg = f"""
📡 LIVE ORACLE DATA - BTC 5m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 PRICES:
   UP: {up:.3f} ({up*100:.1f}%) | DOWN: {down:.3f} ({down*100:.1f}%)

⏰ TIME REMAINING: {minutes}m {seconds}s

📈 CONTEXT:
   OBI: {snapshot['obi']:.4f}
   Velocity: {snapshot['velocity']:.1f} USD/min
   CME Basis: ${snapshot['cme_basis']:.2f}
        """
        await update.message.reply_text(msg)

    async def cmd_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        up, down, slug = get_live_price_from_oracle('btc', '5m')
        if not slug:
            await update.message.reply_text("❌ Cannot fetch market")
            return
        
        time_remaining = self.get_time_remaining(slug)
        minutes = time_remaining // 60
        seconds = time_remaining % 60
        
        size_mult = self.get_size_multiplier(time_remaining)
        window_status = "PRIME WINDOW" if size_mult == 1.0 else "LATE WINDOW" if size_mult == 0.5 else "NOT IN WINDOW"
        
        msg = f"""
⏰ TIME REMAINING: {minutes}m {seconds}s
Window Status: {window_status}
Trade Window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining
        """
        await update.message.reply_text(msg)

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = "📊 REGIME PERFORMANCE\n━━━━━━━━━━━━━━━━━━━━━━━\n"
        for regime, stats in self.regime_stats.items():
            if stats['trades'] > 0:
                wr = stats['wins'] / stats['trades'] * 100
                msg += f"{regime}: {stats['wins']}W/{stats['losses']}L ({wr:.0f}%)\n"
            else:
                msg += f"{regime}: No trades yet\n"
        
        if self.total_trades > 0:
            msg += f"\n📈 Overall Win Rate: {(self.wins/self.total_trades*100):.1f}%"
            msg += f"\n💰 Total PnL: ${self.total_pnl:.2f}"
        
        await update.message.reply_text(msg)

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.cmd_stats(update, context)

    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if os.path.exists(REPORT_FILE):
            await update.message.reply_document(document=open(REPORT_FILE, 'rb'), filename="trade_reports.csv")
        else:
            await update.message.reply_text("No trade reports yet")
        
        if os.path.exists(RESOLVED_FILE):
            await update.message.reply_document(document=open(RESOLVED_FILE, 'rb'), filename="resolved_trades.csv")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = """
🤖 AVAILABLE COMMANDS:
━━━━━━━━━━━━━━━━━━━━━━━
/start     - Start trading
/stop      - Stop trading (no new entries)
/pause     - Pause entries, hold positions
/resume    - Resume trading
/close     - Close all positions immediately
/status    - PnL, win rate, active positions
/check     - Market snapshot (OBI, velocity, CME, regime)
/btc5m     - Live Oracle price verification
/time      - Time remaining in current window
/stats     - Win rate by regime
/report    - Manual hourly report
/export    - Download CSV files
/help      - Show this message

⏰ TRADE WINDOW: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining
💰 Position Size: ${POSITION_SIZE_USD}
        """
        await update.message.reply_text(msg)


# ============================================================
# MAIN
# ============================================================

def main():
    global trader_instance
    
    print("="*60)
    print("Polymarket Trading Bot - 13 Commands")
    print(f"Trade Window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining")
    print("Commands: /start, /stop, /pause, /resume, /close, /status, /check, /btc5m, /time, /stats, /report, /export, /help")
    print("="*60)
    
    init_report_files()
    
    try:
        config = Config()
        telegram_token = config.telegram_token
        print("✅ Telegram token loaded")
    except Exception as e:
        print(f"❌ Config error: {e}")
        return
    
    up, down, slug = get_live_price_from_oracle('btc', '5m')
    if not up:
        print("❌ Oracle not responding")
        return
    
    print(f"✅ Oracle connected: UP={up:.3f}, DOWN={down:.3f}")
    
    trader = RegimeTrader()
    trader_instance = trader
    
    def trading_loop():
        while True:
            try:
                trader.run_cycle()
                time.sleep(TRADE_INTERVAL_SECONDS)
            except Exception as e:
                print(f"Trading loop error: {e}")
                time.sleep(TRADE_INTERVAL_SECONDS)
    
    trading_thread = threading.Thread(target=trading_loop, daemon=True)
    trading_thread.start()
    
    app = Application.builder().token(telegram_token).build()
    
    app.add_handler(CommandHandler("start", trader.cmd_start))
    app.add_handler(CommandHandler("stop", trader.cmd_stop))
    app.add_handler(CommandHandler("pause", trader.cmd_pause))
    app.add_handler(CommandHandler("resume", trader.cmd_resume))
    app.add_handler(CommandHandler("close", trader.cmd_close))
    app.add_handler(CommandHandler("status", trader.cmd_status))
    app.add_handler(CommandHandler("check", trader.cmd_check))
    app.add_handler(CommandHandler("btc5m", trader.cmd_btc5m))
    app.add_handler(CommandHandler("time", trader.cmd_time))
    app.add_handler(CommandHandler("stats", trader.cmd_stats))
    app.add_handler(CommandHandler("report", trader.cmd_report))
    app.add_handler(CommandHandler("export", trader.cmd_export))
    app.add_handler(CommandHandler("help", trader.cmd_help))
    
    print("🚀 Bot is running! Send /help to see commands.")
    print("="*60)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
