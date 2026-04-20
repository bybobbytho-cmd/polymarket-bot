"""
Polymarket Trading Bot with Regime Detection
Time window: ONLY trade when 150-210 seconds remaining (2.5-3.5 min into 5-min market)
Hold until expiration | Silent trading | Hourly reports
"""

import time
import csv
import os
from datetime import datetime

from config import get_live_price_from_oracle, TelegramAlert, Config
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
PRIME_WINDOW_START = 150      # 2.5 minutes left
PRIME_WINDOW_END = 210        # 3.5 minutes left
LATE_WINDOW_START = 90        # 1.5 minutes left
LATE_WINDOW_END = 150         # 2.5 minutes left
# ================================================================

trading_active = True

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
            entry['entry_time'], datetime.utcnow().isoformat(), entry['slug'],
            entry['direction'], entry['outcome'], entry['entry_price'], exit_price,
            entry['size_usd'], entry['shares'], pnl_usd, pnl_percent, result,
            entry['regime'], entry.get('entry_time_remaining'),
            entry.get('entry_obi'), entry.get('entry_velocity'),
            entry.get('entry_cme_basis'), entry.get('entry_distance')
        ])


class RegimeTrader:
    def __init__(self, journal: PolymarketJournal, capital: float, telegram_token=None, telegram_chat_id=None):
        self.journal = journal
        self.positions = {}
        self.total_trades = 0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.last_report_hour = datetime.utcnow().hour
        self.running = True
        self.telegram = None
        
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
        if self.telegram:
            self.telegram.send_message(message)
    
    def get_time_remaining(self, slug):
        try:
            timestamp = int(slug.split('-')[-1])
            window_end = timestamp + 300
            now = int(datetime.utcnow().timestamp())
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
            'timestamp': datetime.utcnow().isoformat()
        }

    def analyze_market(self, market_data):
        distance = abs(market_data['distance_to_strike'])
        time_remaining = market_data['time_remaining']
        
        size_mult = self.get_size_multiplier(time_remaining)
        if size_mult == 0:
            return {
                'execute': False,
                'reason': f"Time window: {time_remaining}s remaining (trade only between {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s)",
                'regime': 'TIME_WINDOW',
                'confidence': 0
            }
        
        regime, trade_dir, confidence, regime_reason = detect_regime(
            obi=market_data['obi'],
            cme_delta=market_data['cme_basis'],
            distance_to_strike=distance,
            velocity=market_data['velocity'],
            rsi_1h=50
        )
        
        execute, direction, _, exec_reason = should_execute(
            regime=regime,
            trade_direction=trade_dir,
            price_position=market_data['distance_to_strike'],
            distance_to_strike=distance,
            confidence=confidence
        )
        
        if execute and direction and confidence >= MIN_CONFIDENCE and trading_active:
            size_usd = POSITION_SIZE_USD * size_mult
            buy_price = market_data['polymarket_up'] if direction == "UP" else market_data['polymarket_down']
            outcome = "YES" if direction == "UP" else "NO"
            shares = size_usd / buy_price if buy_price > 0 else 0
            
            window_type = "PRIME" if size_mult == 1.0 else "LATE"
            
            return {
                'execute': True, 'direction': direction, 'outcome': outcome,
                'price': buy_price, 'size_usd': size_usd, 'shares': shares,
                'confidence': confidence, 'regime': regime,
                'reason': f"[{window_type} WINDOW] {regime_reason} | {exec_reason}"
            }
        
        return {
            'execute': False,
            'reason': f"{regime_reason} | {exec_reason}",
            'regime': regime,
            'confidence': confidence
        }

    def execute_trade(self, analysis, market_data):
        if not analysis['execute'] or market_data['slug'] in self.positions or len(self.positions) >= MAX_POSITIONS:
            return None
        
        position = {
            'slug': market_data['slug'],
            'direction': analysis['direction'],
            'outcome': analysis['outcome'],
            'entry_price': analysis['price'],
            'shares': analysis['shares'],
            'size_usd': analysis['size_usd'],
            'entry_time': datetime.utcnow().isoformat(),
            'entry_time_remaining': market_data['time_remaining'],
            'regime': analysis['regime'],
            'confidence': analysis['confidence'],
            'entry_obi': market_data['obi'],
            'entry_velocity': market_data['velocity'],
            'entry_cme_basis': market_data['cme_basis'],
            'entry_distance': market_data['distance_to_strike']
        }
        
        self.positions[market_data['slug']] = position
        self.total_trades += 1
        
        log_data = {
            'timestamp': market_data['timestamp'],
            'slug': market_data['slug'],
            'time_remaining': market_data['time_remaining'],
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
            'reason': analysis['reason']
        }
        log_trade_decision(log_data)
        return position

    def check_resolutions(self):
        """Check if positions have resolved (market window ended)"""
        slugs_to_remove = []
        for slug, pos in self.positions.items():
            market_data = self.get_current_market_data()
            
            # If market slug changed, previous market has expired/resolved
            if market_data and market_data['slug'] != slug:
                # Market resolved - need to determine actual outcome
                # For now, mark as resolved (you'll need to fetch actual resolution)
                slugs_to_remove.append(slug)
                print(f"📊 Market resolved: {slug}")
        
        for slug in slugs_to_remove:
            del self.positions[slug]

    def send_hourly_report(self):
        current_hour = datetime.utcnow().hour
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
            
            self.send_telegram(report)

    # ========== COMMAND HANDLERS ==========
    
    def cmd_btc5m(self):
        up, down, slug = get_live_price_from_oracle('btc', '5m')
        if not up:
            return "❌ Oracle not responding"
        
        time_remaining = self.get_time_remaining(slug)
        minutes = time_remaining // 60
        seconds = time_remaining % 60
        
        size_mult = self.get_size_multiplier(time_remaining)
        window_status = "✅ PRIME WINDOW" if size_mult == 1.0 else "⚠️ LATE WINDOW" if size_mult == 0.5 else "❌ NOT IN WINDOW"
        snapshot = get_market_snapshot()
        
        return f"""
📡 LIVE ORACLE DATA - BTC 5m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 PRICES:
   UP (YES): {up:.3f} ({up*100:.1f}%)
   DOWN (NO): {down:.3f} ({down*100:.1f}%)

⏰ TIME REMAINING: {minutes}m {seconds}s
   {window_status} (trade window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s)

📈 MARKET CONTEXT:
   OBI: {snapshot['obi']:.4f}
   Velocity: {snapshot['velocity']:.1f} USD/min
   CME Basis: ${snapshot['cme_basis']:.2f}

💡 Bot will only trade if time remaining is between {PRIME_WINDOW_START}-{PRIME_WINDOW_END} seconds.
        """

    def cmd_check(self):
        market_data = self.get_current_market_data()
        if not market_data:
            return "❌ Cannot fetch market data"
        
        distance = abs(market_data['distance_to_strike'])
        time_remaining = market_data['time_remaining']
        
        regime, trade_dir, confidence, reason = detect_regime(
            obi=market_data['obi'], cme_delta=market_data['cme_basis'],
            distance_to_strike=distance, velocity=market_data['velocity'], rsi_1h=50
        )
        
        size_mult = self.get_size_multiplier(time_remaining)
        minutes = time_remaining // 60
        seconds = time_remaining % 60
        
        return f"""
🔍 MARKET CHECK (Manual)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 POLYMARKET:
   UP: {market_data['polymarket_up']:.3f} | DOWN: {market_data['polymarket_down']:.3f}

⏰ TIME: {minutes}m {seconds}s remaining
   {'✅ IN TRADE WINDOW' if size_mult > 0 else '❌ NOT IN TRADE WINDOW'}

📈 DATA:
   OBI: {market_data['obi']:.4f} {'🐋' if abs(market_data['obi']) > 0.6 else '⚖️'}
   Velocity: {market_data['velocity']:.1f} USD/min
   CME Basis: ${market_data['cme_basis']:.2f}

🎯 REGIME: {regime} ({confidence}% confidence)
   {reason}

💡 Bot would {'EXECUTE ' + trade_dir if trade_dir != 'NONE' else 'PASS'} based on current rules.
        """

    def cmd_status(self):
        active = ""
        for slug, pos in self.positions.items():
            active += f"\n• {pos['direction']} @ ${pos['entry_price']:.3f} (${pos['size_usd']:.2f})"
        
        return f"""
🤖 BOT STATUS
━━━━━━━━━━━━━━━━━━━━━━━
Trading Active: {'✅ YES' if trading_active else '❌ NO'}
Total Trades: {self.total_trades}
Wins: {self.wins} | Losses: {self.losses}
Win Rate: {(self.wins/self.total_trades*100) if self.total_trades > 0 else 0:.1f}%
Total PnL: ${self.total_pnl:.2f}
Active Positions:{active or ' None'}
━━━━━━━━━━━━━━━━━━━━━━━
Trade Window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining
Position Size: ${POSITION_SIZE_USD} | Max: {MAX_POSITIONS}
        """

    def cmd_help(self):
        return """
🤖 AVAILABLE COMMANDS:
━━━━━━━━━━━━━━━━━━━━━━━
/start     - Start trading
/stop      - Pause trading
/status    - Show bot status and PnL
/check     - Manual market check (no trade)
/btc5m     - Live prices from Oracle
/export    - Download CSV trade reports
/help      - Show this message

⏰ TRADE WINDOW: Only trades when 2.5-3.5 minutes remaining
💰 Position Size: $1 per trade
📊 Hold until expiration (no early exit)
        """

    def run_cycle(self):
        if not trading_active:
            return
        
        self.check_resolutions()
        self.send_hourly_report()
        
        market_data = self.get_current_market_data()
        if not market_data:
            return
        
        analysis = self.analyze_market(market_data)
        
        if analysis['execute']:
            self.execute_trade(analysis, market_data)
        else:
            log_data = {
                'timestamp': market_data['timestamp'],
                'slug': market_data['slug'],
                'time_remaining': market_data['time_remaining'],
                'regime': analysis['regime'],
                'confidence': analysis['confidence'],
                'verdict': 'PASS',
                'direction': '', 'outcome': '', 'price': '', 'size_usd': '', 'shares': '',
                'obi': market_data['obi'], 'velocity': market_data['velocity'],
                'cme_basis': market_data['cme_basis'],
                'polymarket_up': market_data['polymarket_up'],
                'polymarket_down': market_data['polymarket_down'],
                'distance_to_strike': market_data['distance_to_strike'],
                'reason': analysis['reason']
            }
            log_trade_decision(log_data)

    def stop(self):
        self.running = False


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*60)
    print("Polymarket Trading Bot - Time Window Mode")
    print(f"Trade Window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining (2.5-3.5 min into 5-min market)")
    print("Trades: $1 | Reports: Hourly | Hold until expiration")
    print("="*60)
    
    init_report_files()
    
    try:
        config = Config()
        telegram_token = config.telegram_token
        telegram_chat_id = config.telegram_chat_id
    except Exception as e:
        print(f"⚠️ Config error: {e}")
        telegram_token = None
        telegram_chat_id = None
    
    up, down, slug = get_live_price_from_oracle('btc', '5m')
    if not up:
        print("❌ Oracle not responding")
        return
    
    print(f"✅ Oracle connected: UP={up:.3f}, DOWN={down:.3f}")
    
    journal = PolymarketJournal()
    trader = RegimeTrader(journal, 100.0, telegram_token, telegram_chat_id)
    
    trader.send_telegram(f"🚀 Bot started!\nTrade window: {PRIME_WINDOW_START}-{PRIME_WINDOW_END}s remaining\nHold until expiration | $1 per trade\nCommands: /check, /btc5m, /status, /export")
    
    print("\n🚀 Bot running. Press Ctrl+C to stop.")
    print("="*60)
    
    try:
        while trader.running:
            trader.run_cycle()
            time.sleep(TRADE_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped")
        trader.send_telegram(f"🛑 Bot stopped. Final: {trader.wins}W/{trader.losses}L | PnL: ${trader.total_pnl:.2f}")

if __name__ == "__main__":
    main()
