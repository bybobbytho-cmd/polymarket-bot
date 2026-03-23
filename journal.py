"""
Journal for Polymarket paper trading.
Records trades, generates summaries, and exports data.
"""

import os
import json
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)

class PolymarketJournal:
    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.base_dir = Path("data/journal")
        self.trades_dir = self.base_dir / "trades"
        self.summaries_dir = self.base_dir / "summaries"
        self.trades_dir.mkdir(parents=True, exist_ok=True)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)

        # Daily stats
        self.daily_stats = {
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_volume": 0.0,
            "orders_filled": 0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
        self.open_positions = {}
        self.daily_date = datetime.now().strftime("%Y%m%d")

        # Load existing trades if any
        self._load_today_trades()

    def _load_today_trades(self):
        """Load today's trades from JSONL file."""
        trades_file = self.trades_dir / f"fills_{self.daily_date}.jsonl"
        if not trades_file.exists():
            logger.info(f"No existing trades file for {self.daily_date}")
            return

        logger.info(f"Loading trades from {trades_file}")
        line_count = 0
        with open(trades_file, "r") as f:
            for line in f:
                try:
                    trade = json.loads(line)
                    data = trade["data"]
                    if "pnl" in data and data["pnl"] is not None:
                        # Closed trade
                        self.daily_stats["realized_pnl"] += data["pnl"]
                        self.daily_stats["total_volume"] += float(data["size"])
                        self.daily_stats["orders_filled"] += 1
                        if data["pnl"] > 0:
                            self.daily_stats["winning_trades"] += 1
                        else:
                            self.daily_stats["losing_trades"] += 1
                    else:
                        # Open position
                        self.open_positions[data["market"]] = data
                    line_count += 1
                except Exception as e:
                    logger.error(f"Error parsing trade line: {e}\nLine: {line}")
        logger.info(f"Loaded {line_count} trades. Realized PnL: {self.daily_stats['realized_pnl']}")

    def record_order(self, market: str, side: str, price: float, size: float, order_type: str, pnl: Optional[float] = None):
        """Record a trade (buy or sell)."""
        trade = {
            "timestamp": datetime.now().isoformat(),
            "market": market,
            "side": side,
            "price": price,
            "size": float(size),          # ensure float
            "order_type": order_type,
        }
        if pnl is not None:
            trade["pnl"] = pnl
            # Update daily stats
            self.daily_stats["realized_pnl"] += pnl
            self.daily_stats["total_volume"] += float(size)
            self.daily_stats["orders_filled"] += 1
            if pnl > 0:
                self.daily_stats["winning_trades"] += 1
            else:
                self.daily_stats["losing_trades"] += 1
        else:
            # Open position
            self.open_positions[market] = trade

        # Write to JSONL file
        trades_file = self.trades_dir / f"fills_{self.daily_date}.jsonl"
        with open(trades_file, "a") as f:
            f.write(json.dumps({"type": order_type, "data": trade}) + "\n")
        logger.debug(f"Recorded {order_type} {market} {side} @ {price} size {size}")

    def get_today_summary(self) -> Dict:
        """Return a summary of today's trades."""
        summary = {
            "stats": self.daily_stats.copy(),
            "open_positions": len(self.open_positions),
            "unrealized_pnl": sum(
                self._calculate_unrealized_pnl(pos) for pos in self.open_positions.values()
            ),
        }
        return summary

    def _calculate_unrealized_pnl(self, position: Dict) -> float:
        """Calculate unrealized PnL for an open position using current market price."""
        # This is a placeholder – you should implement actual price fetching
        # For now, we assume no unrealized PnL (or use oracle price)
        return 0.0

    def export_to_csv(self):
        """Export today's trades to a CSV file."""
        trades_file = self.trades_dir / f"fills_{self.daily_date}.jsonl"
        if not trades_file.exists():
            return

        trades = []
        with open(trades_file, "r") as f:
            for line in f:
                trade = json.loads(line)["data"]
                trades.append(trade)

        if not trades:
            return

        df = pd.DataFrame(trades)
        csv_file = self.summaries_dir / f"trades_{self.daily_date}.csv"
        df.to_csv(csv_file, index=False)
