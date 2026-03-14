#!/usr/bin/env python3
"""
Journal System for Polymarket Trading Bot
Handles all logging, trade history, performance tracking, and reporting.
No API keys required - runs entirely on local files.
"""

import os
import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import matplotlib.pyplot as plt
from collections import defaultdict

# ============================================================
# JOURNAL CONFIGURATION
# ============================================================

class JournalConfig:
    """Configuration for the journal system."""
    
    # Base directory for all journal files
    BASE_DIR = Path("data/journal")
    
    # Subdirectories
    TRADES_DIR = BASE_DIR / "trades"
    SIGNALS_DIR = BASE_DIR / "signals"
    POSITIONS_DIR = BASE_DIR / "positions"
    SUMMARIES_DIR = BASE_DIR / "summaries"
    CHARTS_DIR = BASE_DIR / "charts"
    
    # File naming
    DATE_FORMAT = "%Y%m%d"
    TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
    
    @classmethod
    def ensure_dirs(cls):
        """Create all journal directories if they don't exist."""
        for dir_path in [cls.TRADES_DIR, cls.SIGNALS_DIR, cls.POSITIONS_DIR, 
                         cls.SUMMARIES_DIR, cls.CHARTS_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)


# ============================================================
# JOURNAL ENTRY TYPES
# ============================================================

class JournalEntry:
    """Base class for all journal entries."""
    
    def __init__(self, entry_type: str):
        self.entry_type = entry_type
        self.timestamp = datetime.utcnow()
        self.data = {}
    
    def to_dict(self) -> Dict:
        """Convert entry to dictionary for JSON serialization."""
        return {
            "type": self.entry_type,
            "timestamp": self.timestamp.strftime(JournalConfig.TIMESTAMP_FORMAT),
            "data": self.data
        }
    
    def to_json(self) -> str:
        """Convert entry to JSON string."""
        return json.dumps(self.to_dict())


class SignalEntry(JournalEntry):
    """Records every trading signal/opportunity detected."""
    
    def __init__(self, market: str, price: float, confidence: float, action: str):
        super().__init__("signal")
        self.data = {
            "market": market,
            "price": price,
            "confidence": confidence,
            "action": action,  # "buy" or "sell"
            "paper_mode": None  # Will be set later
        }


class OrderEntry(JournalEntry):
    """Records every order placed."""
    
    def __init__(self, market: str, order_type: str, side: str, 
                 price: float, size: float, order_id: Optional[str] = None):
        super().__init__("order")
        self.data = {
            "market": market,
            "order_type": order_type,  # "limit", "market"
            "side": side,  # "buy", "sell"
            "price": price,
            "size": size,
            "order_id": order_id,
            "status": "pending",
            "filled_price": None,
            "filled_size": None
        }


class FillEntry(JournalEntry):
    """Records every filled trade."""
    
    def __init__(self, market: str, side: str, price: float, 
                 size: float, order_id: str, fee: float = 0.0):
        super().__init__("fill")
        self.data = {
            "market": market,
            "side": side,
            "price": price,
            "size": size,
            "order_id": order_id,
            "fee": fee,
            "value": size * price,
            "pnl": 0.0  # Will be calculated when position closes
        }


class PositionEntry(JournalEntry):
    """Tracks open positions."""
    
    def __init__(self, market: str, side: str, entry_price: float, 
                 size: float, entry_order_id: str):
        super().__init__("position")
        self.data = {
            "market": market,
            "side": side,
            "entry_price": entry_price,
            "entry_time": self.timestamp.strftime(JournalConfig.TIMESTAMP_FORMAT),
            "size": size,
            "entry_order_id": entry_order_id,
            "current_price": entry_price,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "exit_price": None,
            "exit_time": None,
            "exit_order_id": None,
            "status": "open"
        }
    
    def close(self, exit_price: float, exit_order_id: str):
        """Close a position and calculate PnL."""
        self.data["exit_price"] = exit_price
        self.data["exit_time"] = datetime.utcnow().strftime(JournalConfig.TIMESTAMP_FORMAT)
        self.data["exit_order_id"] = exit_order_id
        self.data["status"] = "closed"
        
        # Calculate PnL
        if self.data["side"] == "buy":
            self.data["realized_pnl"] = (exit_price - self.data["entry_price"]) * self.data["size"]
        else:  # sell
            self.data["realized_pnl"] = (self.data["entry_price"] - exit_price) * self.data["size"]
        
        self.data["unrealized_pnl"] = 0.0


class RiskEntry(JournalEntry):
    """Records risk management events."""
    
    def __init__(self, event_type: str, details: Dict):
        super().__init__("risk")
        self.data = {
            "event": event_type,  # "daily_loss_limit", "max_drawdown", "position_limit"
            "details": details
        }


class SummaryEntry(JournalEntry):
    """Daily performance summary."""
    
    def __init__(self, date: str, stats: Dict):
        super().__init__("summary")
        self.data = {
            "date": date,
            "stats": stats
        }


# ============================================================
# MAIN JOURNAL CLASS
# ============================================================

class PolymarketJournal:
    """
    Main journal system for recording all bot activity.
    Handles writing, reading, and analyzing trade history.
    """
    
    def __init__(self, paper_mode: bool = True):
        """
        Initialize the journal.
        
        Args:
            paper_mode: If True, marks all entries as paper trades
        """
        JournalConfig.ensure_dirs()
        self.paper_mode = paper_mode
        self.today = datetime.utcnow().strftime(JournalConfig.DATE_FORMAT)
        self.open_positions = self._load_open_positions()
        self.daily_stats = self._init_daily_stats()
        
        print(f"📓 Journal initialized (Paper Mode: {paper_mode})")
        print(f"   Logs directory: {JournalConfig.BASE_DIR}")
    
    def _get_today_file(self, subdir: Path, prefix: str) -> Path:
        """Get today's journal file path."""
        return subdir / f"{prefix}_{self.today}.jsonl"
    
    def _write_entry(self, file_path: Path, entry: JournalEntry):
        """Write a journal entry to file."""
        # Add paper mode flag
        if hasattr(entry, 'data') and 'paper_mode' not in entry.data:
            entry.data['paper_mode'] = self.paper_mode
        
        with open(file_path, 'a') as f:
            f.write(entry.to_json() + '\n')
    
    def _load_open_positions(self) -> Dict[str, PositionEntry]:
        """Load any open positions from today's file."""
        positions = {}
        pos_file = self._get_today_file(JournalConfig.POSITIONS_DIR, "positions")
        
        if pos_file.exists():
            with open(pos_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data['data'].get('status') == 'open':
                            entry = PositionEntry("", "", 0, 0, "")
                            entry.data = data['data']
                            positions[data['data']['market']] = entry
                    except:
                        continue
        
        return positions
    
    def _init_daily_stats(self) -> Dict:
        """Initialize daily statistics."""
        return {
            "signals": 0,
            "orders_placed": 0,
            "orders_filled": 0,
            "total_volume": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
            "largest_win": 0.0,
            "largest_loss": 0.0
        }
    
    # ========================================================
    # RECORDING METHODS
    # ========================================================
    
    def record_signal(self, market: str, price: float, 
                      confidence: float, action: str):
        """Record a trading signal."""
        entry = SignalEntry(market, price, confidence, action)
        file_path = self._get_today_file(JournalConfig.SIGNALS_DIR, "signals")
        self._write_entry(file_path, entry)
        self.daily_stats["signals"] += 1
        
        if self.paper_mode:
            print(f"📝 PAPER SIGNAL: {action.upper()} {market} at ${price:.3f} (conf: {confidence:.1%})")
    
    def record_order(self, market: str, order_type: str, side: str,
                     price: float, size: float, order_id: Optional[str] = None):
        """Record an order placement."""
        entry = OrderEntry(market, order_type, side, price, size, order_id)
        file_path = self._get_today_file(JournalConfig.TRADES_DIR, "orders")
        self._write_entry(file_path, entry)
        self.daily_stats["orders_placed"] += 1
        self.daily_stats["total_volume"] += size
        
        action = "📝 PAPER" if self.paper_mode else "🚀 LIVE"
        print(f"{action} ORDER: {side.upper()} {market} {size} @ ${price:.3f}")
        
        return entry
    
    def record_fill(self, market: str, side: str, price: float,
                    size: float, order_id: str, fee: float = 0.0):
        """Record a filled order."""
        entry = FillEntry(market, side, price, size, order_id, fee)
        file_path = self._get_today_file(JournalConfig.TRADES_DIR, "fills")
        self._write_entry(file_path, entry)
        self.daily_stats["orders_filled"] += 1
        
        # Create or update position
        if side == "buy":
            position = PositionEntry(market, "buy", price, size, order_id)
            self.open_positions[market] = position
            # Write position
            pos_file = self._get_today_file(JournalConfig.POSITIONS_DIR, "positions")
            self._write_entry(pos_file, position)
        else:  # sell - close position
            if market in self.open_positions:
                pos = self.open_positions[market]
                pos.close(price, order_id)
                # Update position file
                pos_file = self._get_today_file(JournalConfig.POSITIONS_DIR, "positions")
                self._write_entry(pos_file, pos)
                
                # Update stats
                pnl = pos.data['realized_pnl']
                self.daily_stats["realized_pnl"] += pnl
                if pnl > 0:
                    self.daily_stats["winning_trades"] += 1
                    self.daily_stats["largest_win"] = max(self.daily_stats["largest_win"], pnl)
                elif pnl < 0:
                    self.daily_stats["losing_trades"] += 1
                    self.daily_stats["largest_loss"] = min(self.daily_stats["largest_loss"], pnl)
                
                del self.open_positions[market]
        
        action = "📝 PAPER" if self.paper_mode else "🚀 LIVE"
        print(f"{action} FILL: {side.upper()} {market} {size} @ ${price:.3f}")
    
    def record_risk_event(self, event_type: str, details: Dict):
        """Record a risk management event."""
        entry = RiskEntry(event_type, details)
        file_path = self._get_today_file(JournalConfig.TRADES_DIR, "risk")
        self._write_entry(file_path, entry)
        
        print(f"⚠️ RISK EVENT: {event_type} - {details}")
    
    # ========================================================
    # ANALYSIS METHODS
    # ========================================================
    
    def get_today_summary(self) -> Dict:
        """Get today's trading summary."""
        # Update unrealized PnL from open positions
        unrealized = 0.0
        for pos in self.open_positions.values():
            if pos.data['current_price']:
                if pos.data['side'] == "buy":
                    pnl = (pos.data['current_price'] - pos.data['entry_price']) * pos.data['size']
                else:
                    pnl = (pos.data['entry_price'] - pos.data['current_price']) * pos.data['size']
                unrealized += pnl
        
        self.daily_stats["unrealized_pnl"] = unrealized
        
        return {
            "date": self.today,
            "paper_mode": self.paper_mode,
            "stats": self.daily_stats,
            "open_positions": len(self.open_positions),
            "total_pnl": self.daily_stats["realized_pnl"] + unrealized
        }
    
    def generate_daily_report(self) -> str:
        """Generate a human-readable daily report."""
        summary = self.get_today_summary()
        stats = summary['stats']
        
        report = []
        report.append("=" * 60)
        report.append(f"📊 TRADING SUMMARY - {self.today}")
        report.append("=" * 60)
        report.append(f"Mode: {'📝 PAPER' if self.paper_mode else '🚀 LIVE'}")
        report.append(f"Signals detected: {stats['signals']}")
        report.append(f"Orders placed: {stats['orders_placed']}")
        report.append(f"Orders filled: {stats['orders_filled']}")
        report.append(f"Total volume: ${stats['total_volume']:.2f}")
        report.append("")
        report.append(f"Realized PnL: ${stats['realized_pnl']:.2f}")
        report.append(f"Unrealized PnL: ${stats['unrealized_pnl']:.2f}")
        report.append(f"Total PnL: ${summary['total_pnl']:.2f}")
        report.append("")
        report.append(f"Winning trades: {stats['winning_trades']}")
        report.append(f"Losing trades: {stats['losing_trades']}")
        if stats['winning_trades'] + stats['losing_trades'] > 0:
            win_rate = stats['winning_trades'] / (stats['winning_trades'] + stats['losing_trades'])
            report.append(f"Win rate: {win_rate:.1%}")
        report.append(f"Largest win: ${stats['largest_win']:.2f}")
        report.append(f"Largest loss: ${stats['largest_loss']:.2f}")
        report.append("")
        report.append(f"Open positions: {summary['open_positions']}")
        for market, pos in self.open_positions.items():
            report.append(f"  • {market}: {pos.data['side']} {pos.data['size']} @ ${pos.data['entry_price']:.3f}")
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def save_daily_report(self):
        """Save daily report to file."""
        report = self.generate_daily_report()
        report_file = JournalConfig.SUMMARIES_DIR / f"summary_{self.today}.txt"
        
        with open(report_file, 'w') as f:
            f.write(report)
        
        print(f"\n📄 Daily report saved to: {report_file}")
        
        # Also save summary as JSONL
        summary_entry = SummaryEntry(self.today, self.daily_stats)
        summary_file = JournalConfig.SUMMARIES_DIR / f"summary_{self.today}.jsonl"
        self._write_entry(summary_file, summary_entry)
    
    def export_to_csv(self):
        """Export trades to CSV for analysis in Excel."""
        csv_file = JournalConfig.SUMMARIES_DIR / f"trades_{self.today}.csv"
        
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Market', 'Side', 'Price', 'Size', 'PnL', 'Paper Mode'])
            
            # Read fills from today
            fills_file = self._get_today_file(JournalConfig.TRADES_DIR, "fills")
            if fills_file.exists():
                with open(fills_file, 'r') as jf:
                    for line in jf:
                        try:
                            data = json.loads(line)
                            if data['type'] == 'fill':
                                d = data['data']
                                writer.writerow([
                                    data['timestamp'],
                                    d['market'],
                                    d['side'],
                                    d['price'],
                                    d['size'],
                                    d.get('pnl', 0),
                                    d.get('paper_mode', True)
                                ])
                        except:
                            continue
        
        print(f"📊 CSV export saved to: {csv_file}")
    
    def plot_equity_curve(self):
        """Generate equity curve chart."""
        # Collect all PnL events
        pnl_events = []
        timestamps = []
        cumulative = 0
        
        fills_file = self._get_today_file(JournalConfig.TRADES_DIR, "fills")
        if fills_file.exists():
            with open(fills_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data['type'] == 'fill' and 'pnl' in data['data']:
                            pnl_events.append(data['data']['pnl'])
                            timestamps.append(data['timestamp'])
                    except:
                        continue
        
        if pnl_events:
            # Calculate cumulative PnL
            cumulative_pnl = []
            running_total = 0
            for pnl in pnl_events:
                running_total += pnl
                cumulative_pnl.append(running_total)
            
            # Create plot
            plt.figure(figsize=(10, 6))
            plt.plot(cumulative_pnl, marker='o', linestyle='-', linewidth=2)
            plt.title('Equity Curve - Cumulative PnL')
            plt.xlabel('Trade Number')
            plt.ylabel('Cumulative PnL ($)')
            plt.grid(True, alpha=0.3)
            
            # Save chart
            chart_file = JournalConfig.CHARTS_DIR / f"equity_{self.today}.png"
            plt.savefig(chart_file)
            plt.close()
            
            print(f"📈 Equity chart saved to: {chart_file}")


# ============================================================
# TEST FUNCTION
# ============================================================

def test_journal():
    """Test the journal system with sample data."""
    print("🔍 Testing Journal System...")
    
    # Create journal in paper mode
    journal = PolymarketJournal(paper_mode=True)
    
    # Simulate some trading activity
    print("\n📝 Simulating paper trades...")
    
    # Record signals
    journal.record_signal("BTC_5m", 0.475, 0.85, "buy")
    journal.record_signal("BTC_5m", 0.525, 0.90, "sell")
    
    # Place orders
    order1 = journal.record_order("BTC_5m", "limit", "buy", 0.475, 1.00)
    order2 = journal.record_order("BTC_5m", "limit", "sell", 0.525, 1.00)
    
    # Record fills
    journal.record_fill("BTC_5m", "buy", 0.475, 1.00, "order123", fee=0.01)
    journal.record_fill("BTC_5m", "sell", 0.525, 1.00, "order456", fee=0.01)
    
    # Another trade
    journal.record_signal("ETH_5m", 0.635, 0.75, "buy")
    journal.record_order("ETH_5m", "market", "buy", 0.635, 1.00)
    journal.record_fill("ETH_5m", "buy", 0.635, 1.00, "order789", fee=0.01)
    
    # This one is still open
    journal.record_signal("ETH_15m", 0.435, 0.80, "buy")
    journal.record_order("ETH_15m", "limit", "buy", 0.435, 1.00)
    journal.record_fill("ETH_15m", "buy", 0.435, 1.00, "order012", fee=0.01)
    
    # Generate reports
    print("\n" + journal.generate_daily_report())
    
    # Save reports
    journal.save_daily_report()
    journal.export_to_csv()
    journal.plot_equity_curve()
    
    print("\n✅ Journal test complete!")
    print(f"   Check {JournalConfig.BASE_DIR} for output files")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    test_journal()
