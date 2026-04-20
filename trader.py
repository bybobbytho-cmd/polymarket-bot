"""
Polymarket Trading Bot with Regime Detection
Telegram Commands | $1 per trade | Full logging | Pattern tracking
"""

import time
import requests
import csv
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from config import get_live_price_from_oracle, TelegramAlert, Config
from market_data import get_market_snapshot
from regime import detect_regime
from executor import should_execute
from journal import PolymarketJournal

# ==================== CONFIGURABLE PARAMETERS ====================
POSITION_SIZE_USD = 1.0      # $1 per trade
MAX_POSITIONS = 3             # Maximum concurrent positions
MIN_CONFIDENCE = 70           # Minimum confidence % to execute
TRADE_INTERVAL_SECONDS = 60   # Check every 60 seconds
REPORT_FILE = "trade_reports.csv"
RESOLVED_FILE = "resolved_trades.csv"
PATTERN_FILE = "pattern_analysis.csv"
# ================================================================

# Global flag for trading state
trading_active = True

def init_report_files():
    """Create CSV files for trade reports if they don't exist"""
    
    # Trade decisions log
    if not os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "slug", "regime", "confidence", "verdict",
                "direction", "outcome", "price", "size_usd", "shares",
                "obi", "velocity", "cme_basis", "polymarket_up", 
                "polymarket_down", "distance_to_strike", "rsi_1h",
                "time_remaining_sec", "reason"
            ])
    
    # Resolved trades log
    if not os.path.exists(RESOLVED_FILE):
        with open(RESOLVED_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "entry_timestamp", "exit_timestamp", "slug", "direction", 
                "outcome", "entry_price", "exit_price", "size_usd", 
                "shares", "pnl_usd", "pnl_percent", "result", "regime",
                "entry_obi", "entry_velocity", "entry_cme_basis", "entry_distance"
            ])
    
    # Pattern analysis log (hourly aggregated)
    if not os.path.exists(PATTERN_FILE):
        with open(PATTERN_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "date_hour", "total_decisions", "executes", "passes",
                "wins", "losses", "win_rate", "avg_confidence",
                "regime_whale_wins", "regime_gravity_wins", "regime_chaos_wins"
            ])

def log_trade_decision(data):
    """Log trade decision to CSV"""
    with open(REPORT_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data.get('timestamp'),
            data.get('slug'),
            data.get('regime'),
            data.get('confidence'),
            data.get('verdict'),
            data.get('direction'),
            data.get('outcome'),
            data.get('price'),
            data.get('size_usd'),
            data.get('shares'),
            data.get('obi'),
            data.get('velocity'),
            data.get('cme_basis'),
            data.get('polymarket_up'),
            data.get('polymarket_down'),
            data.get('distance_to_strike'),
            data.get('rsi_1h'),
            data.get('time_remaining'),
            data.get('reason')
        ])

def log_resolved_trade(entry, exit_price, pnl_usd, pnl_percent, result):
    """Log resolved trade to CSV with full context for pattern analysis"""
    with open(RESOLVED_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            entry['entry_time'],
            datetime.utcnow().isoformat(),
            entry['slug'],
            entry['direction'],
            entry['outcome'],
            entry['entry_price'],
            exit_price,
            entry['size_usd'],
            entry['shares'],
            pnl_usd,
            pnl_percent,
            result,
            entry['regime'],
            entry.get('entry_obi'),
            entry.get('entry_velocity'),
            entry.get('entry_cme_basis'),
            entry.get('entry_distance')
        ])


class RegimeTrader:
    def __init__(self, journal: PolymarketJournal, capital: float, telegram_token=None, telegram_chat_id=None):
        self.journal = journal
        self.capital = capital
        self.positions = {}  # slug -> position details
        self.total_trades = 0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.last_report_hour = datetime.utcnow().hour
        self.running = True
        self.telegram = None
        
        # Pattern tracking
        self.regime_stats = {
            'WHALE_REGIME': {'wins': 0, 'losses': 0, 'trades': 0},
            'GRAVITY_REGIME': {'wins': 0, 'losses': 0, 'trades': 0},
            'RSI_EXTREME': {'wins': 0, 'losses': 0, 'trades': 0},
            'DEAD_ZONE': {'wins': 0, 'losses': 0, 'trades': 0},
            'CHAOS_REGIME': {'wins': 0, 'losses': 0, 'trades': 0}
        }
        
        if telegram_token and telegram_chat_id:
            self.telegram = TelegramAlert(telegram_token, telegram_chat_id)
    
    def send_telegram(self, message):
        """Send Telegram alert"""
        if self.telegram:
            self.telegram.send_message(message)
        else:
            print(f"📱 TELEGRAM: {message}")
    
    def get_current_market_data(self):
        """Get all data needed for trading decision"""
        
        # Get Polymarket prices from Oracle
        up, down, slug = get_live_price_from_oracle('btc', '5m')
        if not up:
            return None
        
        # Get Binance/CME data
        snapshot = get_market_snapshot()
        
        # Calculate distance to strike
        strike = snapshot['spot_price'] - 50 if snapshot['spot_price'] else 75000
        distance = snapshot['spot_price'] - strike if snapshot['spot_price'] else 0
        
        # Calculate time remaining in market (approx 5 minutes)
        time_remaining = 300  # Default 5 minutes
        
        return {
            'slug': slug,
            'polymarket_up': up,
            'polymarket_down': down,
            'spot_price': snapshot['spot_price'],
            'obi': snapshot['obi'],
            'velocity': snapshot['velocity'],
            'cme_basis': snapshot['cme_basis'],
            'distance_to_strike': distance,
            'time_remaining': time_remaining,
            'rsi_1h': 50,  # Placeholder
            'timestamp': datetime.utcnow().isoformat()
        }

    def analyze_market(self, market_data):
        """Run regime detection and return trade verdict"""
        
        distance = abs(market_data['distance_to_strike'])
        
        # Detect regime
        regime, trade_dir, confidence, regime_reason = detect_regime(
            obi=market_data['obi'],
            cme_delta=market_data['cme_basis'],
            distance_to_strike=distance,
            velocity=market_data['velocity'],
            rsi_1h=market_data.get('rsi_1h', 50)
        )
        
        # Get execution decision
        execute, direction, size_mult, exec_reason = should_execute(
            regime=regime,
            trade_direction=trade_dir,
            price_position=market_data['distance_to_strike'],
            distance_to_strike=distance,
            confidence=confidence
        )
        
        # Calculate position size
        if execute and direction and confidence >= MIN_CONFIDENCE and trading_active:
            size_usd = POSITION_SIZE_USD * size_mult
            
            if direction == "UP":
                buy_price = market_data['polymarket_up']
                outcome = "YES"
            else:
                buy_price = market_data['polymarket_down']
                outcome = "NO"
            
            shares = size_usd / buy_price if buy_price > 0 else 0
            
            return {
                'execute': True,
                'direction': direction,
                'outcome': outcome,
                'price': buy_price,
                'size_usd': size_usd,
                'shares': shares,
                'confidence': confidence,
                'regime': regime,
                'reason': f"{regime_reason} | {exec_reason}"
            }
        
        return {
            'execute': False,
            'reason': f"{regime_reason} | {exec_reason}",
            'regime': regime,
            'confidence': confidence
        }

    def execute_trade(self, analysis, market_data):
        """Execute a trade"""
        if not analysis['execute']:
            return None
        
        slug = market_data['slug']
        if slug in self.positions:
            return None
        
        if len(self.positions) >= MAX_POSITIONS:
            return None
        
        position = {
            'slug': slug,
            'direction': analysis['direction'],
            'outcome': analysis['outcome'],
            'entry_price': analysis['price'],
            'shares': analysis['shares'],
            'size_usd': analysis['size_usd'],
            'entry_time': datetime.utcnow().isoformat(),
            'regime': analysis['regime'],
            'confidence': analysis['confidence'],
            'entry_obi': market_data['obi'],
            'entry_velocity': market_data['velocity'],
            'entry_cme_basis': market_data['cme_basis'],
            'entry_distance': market_data['distance_to_strike']
        }
        
        self.positions[slug] = position
        self.total_trades += 1
        
        # Log to journal
        self.journal.record_signal(
            market=slug,
            price=analysis['price'],
            confidence=analysis['confidence'],
            action=f"BUY_{analysis['outcome']}"
        )
        
        # Log to CSV
        log_data = {
            'timestamp': market_data['timestamp'],
            'slug': slug,
            'regime': analysis['regime'],
            'confidence': analysis['confidence'],
            'verdict': 'EXECUTE',
            'direction': analysis['direction'],
            'outcome': analysis['outcome'],
            'price': analysis['price'],
            'size_usd': analysis['size_usd'],
            'shares': analysis['shares'],
            'obi': market_data['obi'],
            'velocity': market_data['velocity'],
            'cme_basis': market_data['cme_basis'],
            'polymarket_up': market_data['polymarket_up'],
            'polymarket_down': market_data['polymarket_down'],
            'distance_to_strike': market_data['distance_to_strike'],
            'rsi_1h': market_data.get('rsi_1h', 50),
            'time_remaining': market_data.get('time_remaining', 300),
            'reason': analysis['reason']
        }
        log_trade_decision(log_data)
        
        # Send Telegram alert
        alert = f"""
🚨 TRADE EXECUTED
Direction: {analysis['direction']} ({analysis['outcome']})
Price: ${analysis['price']:.3f}
Size: ${analysis['size_usd']:.2f}
Regime: {analysis['regime']}
Confidence: {analysis['confidence']}%
OBI: {market_data['obi']:.3f}
Velocity: {market_data['velocity']:.1f}
CME Basis: ${market_data['cme_basis']:.1f}
Distance: ${market_data['distance_to_strike']:.0f}
Reason: {analysis['reason']}
        """
        self.send_telegram(alert)
        
        print(f"\n✅ EXECUTED: {analysis['direction']}")
        print(f"   Price: ${analysis['price']:.3f}")
        print(f"   Size: ${analysis['size_usd']:.2f}")
        print(f"   Regime: {analysis['regime']}")
        
        return position

    def check_resolutions(self):
        """Check if any positions have resolved"""
        slugs_to_remove = []
        
        for slug, pos in self.positions.items():
            market_data = self.get_current_market_data()
            if not market_data:
                continue
            
            if market_data['slug'] != slug:
                slugs_to_remove.append(slug)
        
        return slugs_to_remove

    def check_exits(self):
        """Check if any positions should be closed"""
        slugs_to_remove = []
        
        for slug, pos in self.positions.items():
            market_data = self.get_current_market_data()
            if not market_data or market_data['slug'] != slug:
                continue
            
            if pos['outcome'] == 'YES':
                current_price = market_data['polymarket_up']
            else:
                current_price = market_data['polymarket_down']
            
            pnl_usd = (current_price - pos['entry_price']) * pos['shares']
            pnl_percent = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            
            should_exit = False
            exit_reason = ""
            
            if pnl_percent >= 20:
                should_exit = True
                exit_reason = "Take profit (20%)"
            elif pnl_percent <= -30:
                should_exit = True
                exit_reason = "Stop loss (30%)"
            
            if should_exit:
                result = "WIN" if pnl_usd > 0 else "LOSS"
                
                if result == "WIN":
                    self.wins += 1
                    self.regime_stats[pos['regime']]['wins'] += 1
                else:
                    self.losses += 1
                    self.regime_stats[pos['regime']]['losses'] += 1
                self.regime_stats[pos['regime']]['trades'] += 1
                
                log_resolved_trade(pos, current_price, pnl_usd, pnl_percent, result)
                
                alert = f"""
📊 POSITION CLOSED
Slug: {slug}
Direction: {pos['direction']}
Entry: ${pos['entry_price']:.3f} → Exit: ${current_price:.3f}
PnL: ${pnl_usd:.2f} ({pnl_percent:.1f}%)
Result: {result}
Regime: {pos['regime']}
Reason: {exit_reason}
                """
                self.send_telegram(alert)
                
                print(f"\n📤 EXIT: {slug}")
                print(f"   PnL: ${pnl_usd:.2f} ({pnl_percent:.1f}%)")
                print(f"   Result: {result}")
                
                self.total_pnl += pnl_usd
                slugs_to_remove.append(slug)
        
        for slug in slugs_to_remove:
            del self.positions[slug]

    def generate_pattern_report(self):
        """Generate and send pattern analysis report"""
        current_hour = datetime.utcnow().hour
        
        if current_hour != self.last_report_hour:
            self.last_report_hour = current_hour
            
            # Calculate win rates by regime
            report = f"""
📈 PATTERN ANALYSIS REPORT (Hour {current_hour-1}:00 - {current_hour}:00)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Trades: {self.total_trades}
Wins: {self.wins} | Losses: {self.losses}
Win Rate: {(self.wins/self.total_trades*100) if self.total_trades > 0 else 0:.1f}%
Total PnL: ${self.total_pnl:.2f}

📊 REGIME PERFORMANCE:
"""
            for regime, stats in self.regime_stats.items():
                if stats['trades'] > 0:
                    win_rate = stats['wins'] / stats['trades'] * 100
                    report += f"{regime}: {stats['wins']}W/{stats['losses']}L ({win_rate:.0f}%)\n"
            
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Active Positions: {len(self.positions)}
            """
            self.send_telegram(report)
            print(f"\n📊 Pattern report sent")

    def get_status_message(self):
        """Generate status message for /status command"""
        active_positions = ""
        for slug, pos in self.positions.items():
            active_positions += f"\n• {pos['direction']} @ ${pos['entry_price']:.3f} (${pos['size_usd']:.2f})"
        
        if not active_positions:
            active_positions = "\n• No active positions"
        
        return f"""
🤖 BOT STATUS
━━━━━━━━━━━━━━━━━━━━━━━
Trading Active: {'✅ YES' if trading_active else '❌ NO'}
Total Trades: {self.total_trades}
Wins: {self.wins} | Losses: {self.losses}
Win Rate: {(self.wins/self.total_trades*100) if self.total_trades > 0 else 0:.1f}%
Total PnL: ${self.total_pnl:.2f}
Active Positions:{active_positions}
━━━━━━━━━━━━━━━━━━━━━━━
Position Size: ${POSITION_SIZE_USD}
Max Positions: {MAX_POSITIONS}
Min Confidence: {MIN_CONFIDENCE}%
        """

    def run_cycle(self):
        """Main trading cycle"""
        if not trading_active:
            return
        
        print(f"\n{'='*60}")
        print(f"🔄 Trading Cycle - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   Active positions: {len(self.positions)}")
        print(f"   Total PnL: ${self.total_pnl:.2f}")
        print(f"{'='*60}")
        
        self.check_exits()
        self.generate_pattern_report()
        
        market_data = self.get_current_market_data()
        if not market_data:
            print("❌ No market data available")
            return
        
        print(f"\n📊 Market: {market_data['slug']}")
        print(f"   UP: {market_data['polymarket_up']:.3f} | DOWN: {market_data['polymarket_down']:.3f}")
        print(f"   OBI: {market_data['obi']:.4f} | Velocity: {market_data['velocity']:.2f}")
        print(f"   CME Basis: ${market_data['cme_basis']:.2f}")
        
        analysis = self.analyze_market(market_data)
        
        print(f"\n🎯 Regime: {analysis['regime']} (Confidence: {analysis['confidence']}%)")
        
        if analysis['execute']:
            print(f"   ✅ Verdict: EXECUTE {analysis['direction']}")
            self.execute_trade(analysis, market_data)
        else:
            print(f"   ❌ Verdict: PASS")
            print(f"   Reason: {analysis['reason']}")
            
            log_data = {
                'timestamp': market_data['timestamp'],
                'slug': market_data['slug'],
                'regime': analysis['regime'],
                'confidence': analysis['confidence'],
                'verdict': 'PASS',
                'direction': '',
                'outcome': '',
                'price': '',
                'size_usd': '',
                'shares': '',
                'obi': market_data['obi'],
                'velocity': market_data['velocity'],
                'cme_basis': market_data['cme_basis'],
                'polymarket_up': market_data['polymarket_up'],
                'polymarket_down': market_data['polymarket_down'],
                'distance_to_strike': market_data['distance_to_strike'],
                'rsi_1h': market_data.get('rsi_1h', 50),
                'time_remaining': market_data.get('time_remaining', 300),
                'reason': analysis['reason']
            }
            log_trade_decision(log_data)

    def stop(self):
        self.running = False


# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

def handle_start(update, context):
    """/start command - begin trading"""
    global trading_active
    trading_active = True
    update.message.reply_text("✅ Trading started! I'll execute $1 trades when conditions are met.")

def handle_stop(update, context):
    """/stop command - pause trading"""
    global trading_active
    trading_active = False
    update.message.reply_text("⏸️ Trading paused. Use /start to resume.")

def handle_status(update, context, trader):
    """/status command - show current status"""
    status = trader.get_status_message()
    update.message.reply_text(status)

def handle_export(update, context):
    """/export command - send CSV files"""
    if os.path.exists(REPORT_FILE):
        update.message.reply_document(document=open(REPORT_FILE, 'rb'), filename="trade_reports.csv")
    if os.path.exists(RESOLVED_FILE):
        update.message.reply_document(document=open(RESOLVED_FILE, 'rb'), filename="resolved_trades.csv")
    update.message.reply_text("📁 CSV files sent. Use these for pattern analysis.")


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*60)
    print("Polymarket Trading Bot with Pattern Tracking")
    print("Position Size: $1 per trade")
    print("Telegram Commands: /start, /stop, /status, /export")
    print("="*60)
    
    init_report_files()
    print("\n📁 Report files initialized")
    
    # Load config for Telegram
    try:
        config = Config()
        telegram_token = config.telegram_token
        telegram_chat_id = config.telegram_chat_id
        print("✅ Telegram config loaded")
    except Exception as e:
        print(f"⚠️ Telegram not configured: {e}")
        telegram_token = None
        telegram_chat_id = None
    
    # Test Oracle connection
    print("\n🔗 Testing Oracle connection...")
    up, down, slug = get_live_price_from_oracle('btc', '5m')
    if up:
        print(f"   ✅ Oracle connected!")
        print(f"   Current BTC 5m: UP={up:.3f}, DOWN={down:.3f}")
    else:
        print("   ❌ Oracle not responding. Exiting.")
        return
    
    # Initialize trader
    journal = PolymarketJournal()
    trader = RegimeTrader(journal, capital=100.0, telegram_token=telegram_token, telegram_chat_id=telegram_chat_id)
    
    # Send startup message
    trader.send_telegram("🚀 Bot started! Trading with $1 per position.\nCommands: /start, /stop, /status, /export")
    
    print("\n🚀 Bot is running. Press Ctrl+C to stop.")
    print("📊 Reports saved to: trade_reports.csv, resolved_trades.csv, pattern_analysis.csv")
    print("="*60)
    
    try:
        while trader.running:
            trader.run_cycle()
            print(f"\n⏰ Waiting {TRADE_INTERVAL_SECONDS} seconds...")
            time.sleep(TRADE_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped")
        print(f"\n📊 FINAL STATISTICS:")
        print(f"   Total Trades: {trader.total_trades}")
        print(f"   Wins: {trader.wins} | Losses: {trader.losses}")
        print(f"   Win Rate: {(trader.wins/trader.total_trades*100) if trader.total_trades > 0 else 0:.1f}%")
        print(f"   Total PnL: ${trader.total_pnl:.2f}")
        
        trader.send_telegram(f"🛑 Bot stopped.\nFinal: {trader.wins}W/{trader.losses}L | PnL: ${trader.total_pnl:.2f}")

if __name__ == "__main__":
    main()
