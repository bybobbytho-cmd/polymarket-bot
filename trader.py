"""
Paper Trader for Polymarket – with realistic order book execution and fees.
"""

import os
import time
import requests
from datetime import datetime
from typing import Dict, Optional, Tuple

from config import MinuteMarketFinder
from journal import PolymarketJournal
from orderbook import get_token_id_from_slug, simulate_market_order

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, 
                 oracle_url: str, capital: float = 10.0):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.capital = capital
        self.peak_capital = capital
        self.positions = {}  # market_slug -> {'side': 'YES'/'NO', 'entry_price': float, 'size': float}
        self.paused = False
        self.consecutive_losses = 0
        self.daily_stats = {'realized_pnl': 0.0, 'orders_filled': 0,
                            'winning_trades': 0, 'losing_trades': 0}
        
        # Strategy parameters
        self.ENTRY_THRESHOLD = 0.20        # buy YES when up_price < 0.20, etc.
        self.TAKE_PROFIT_PCT = 0.10        # 10% profit
        self.STOP_LOSS_PCT = 0.20          # 20% loss
        self.CONSECUTIVE_LOSS_LIMIT = 3
        self.DAILY_LOSS_LIMIT = 5.0        # in USD
        
        # Realism settings
        self.USE_ORDERBOOK = True           # set to False to fall back to oracle price
        self.FEE_PCT = 0.01                # 1% fee on winning trades

    def fetch_price_from_oracle(self, asset: str, interval: str) -> Tuple[Optional[float], Optional[float], Optional[dict]]:
        """Get up/down prices and raw data from the oracle."""
        if not self.oracle_url:
            return None, None, None
        try:
            url = f"{self.oracle_url}/api/price/{asset}/{interval}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('up'), data.get('down'), data
        except Exception as e:
            print(f"Oracle error: {e}")
        return None, None, None

    def get_market_price(self, slug: str, side: str, action: str) -> float:
        """
        Get the price at which we can actually trade.
        side: 'YES' or 'NO'
        action: 'enter' or 'exit'
        Returns price per share.
        """
        if not self.USE_ORDERBOOK:
            # Fallback: use oracle midpoint
            # We need to find the market's asset and interval from slug – simplified for now
            # In reality you'd parse slug or ask the oracle. We'll assume we have a way.
            # For simplicity, we'll return the current oracle price (which your original code does)
            # Placeholder: call the method that gets current price from your existing logic.
            return self._get_oracle_midpoint(slug, side)

        # Use order book
        yes_token, no_token = get_token_id_from_slug(slug)
        token_id = yes_token if side == 'YES' else no_token
        if not token_id:
            # Fallback to oracle
            return self._get_oracle_midpoint(slug, side)

        if action == 'enter':
            # Buying: we pay the ask
            avg_price, _ = simulate_market_order(token_id, 'buy', 1.0)  # simulate buying 1 share
            return avg_price
        else:  # exit
            # Selling: we receive the bid
            avg_price, _ = simulate_market_order(token_id, 'sell', 1.0)  # simulate selling 1 share
            return avg_price

    def _get_oracle_midpoint(self, slug: str, side: str) -> float:
        """Fallback: get the current oracle price (midpoint) for the market."""
        # This is a simplified version; you should adapt to your existing method
        # For now, we'll assume the oracle gives up/down prices.
        # We need to map slug back to asset and interval. In your original trader,
        # you probably already have a way to get the current price. We'll call that.
        # As a placeholder, return 0.5. You should replace this with your actual logic.
        # For example: up, down, _ = self.fetch_price_from_oracle(asset, interval)
        # Then return up if side == 'YES' else down.
        print(f"Warning: Falling back to oracle midpoint for {slug} {side}")
        return 0.5

    def run_cycle(self):
        """Main trading loop – called every 60 seconds."""
        if self.paused:
            return

        # Check daily loss limit
        if self.daily_stats['realized_pnl'] <= -self.DAILY_LOSS_LIMIT:
            print(f"Daily loss limit reached. Pausing.")
            self.paused = True
            return

        # For now, we'll trade both BTC 5m and 15m markets
        # In your original code, you likely have a list of markets to check.
        # We'll generate signals for the current windows.
        now = int(time.time())
        for market_base in ['btc-updown-5m', 'btc-updown-15m']:
            if market_base.endswith('5m'):
                period = 5 * 60
            else:
                period = 15 * 60
            window_start = now - (now % period)
            slug = f"{market_base}-{window_start}"
            market_data = self.market_finder.get_market_by_slug(slug)
            if not market_data:
                continue

            # Get oracle prices
            # We need asset and interval. From slug, we can parse.
            # Let's assume we have a method to get them.
            # For demonstration, we'll use a placeholder.
            # Replace with your actual logic.
            up, down, _ = self.fetch_price_from_oracle('btc', '5m')  # adjust
            if up is None or down is None:
                continue

            # Entry logic
            # Example: buy YES when up < 0.20
            if up < self.ENTRY_THRESHOLD and slug not in self.positions:
                price = self.get_market_price(slug, 'YES', 'enter')
                if price > 0:
                    self._enter_position(slug, 'YES', price, 1.0)

            # Similarly for NO
            if down < self.ENTRY_THRESHOLD and slug not in self.positions:
                price = self.get_market_price(slug, 'NO', 'enter')
                if price > 0:
                    self._enter_position(slug, 'NO', price, 1.0)

            # Check existing positions for take profit / stop loss
            if slug in self.positions:
                pos = self.positions[slug]
                current_price = self.get_market_price(slug, pos['side'], 'exit')
                if current_price <= 0:
                    continue
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                if pos['side'] == 'NO':
                    pnl_pct = -pnl_pct  # because NO price moves opposite to YES

                if pnl_pct >= self.TAKE_PROFIT_PCT:
                    self._exit_position(slug, current_price, profit=True)
                elif pnl_pct <= -self.STOP_LOSS_PCT:
                    self._exit_position(slug, current_price, profit=False)

    def _enter_position(self, slug: str, side: str, price: float, size: float):
        """Record a new paper position."""
        if price <= 0:
            return
        self.positions[slug] = {'side': side, 'entry_price': price, 'size': size}
        self.capital -= size * price
        if self.capital < 0:
            # This should not happen, but cap at 0
            self.capital = 0
        self.journal.record_order(slug, side, price, size, 'BUY')
        print(f"Entered {slug} {side} @ {price:.3f}")

    def _exit_position(self, slug: str, price: float, profit: bool):
        """Close a position, apply fee on profit."""
        pos = self.positions.pop(slug)
        if pos['side'] == 'YES':
            gross_pnl = (price - pos['entry_price']) * pos['size']
        else:
            gross_pnl = (pos['entry_price'] - price) * pos['size']

        # Apply 1% fee on winning trades
        if gross_pnl > 0:
            fee = gross_pnl * self.FEE_PCT
            net_pnl = gross_pnl - fee
        else:
            net_pnl = gross_pnl

        self.capital += (pos['size'] * price) + net_pnl  # we get the sale proceeds + pnl
        self.peak_capital = max(self.peak_capital, self.capital)

        # Update stats
        self.daily_stats['realized_pnl'] += net_pnl
        self.daily_stats['orders_filled'] += 1
        if net_pnl > 0:
            self.daily_stats['winning_trades'] += 1
            self.consecutive_losses = 0
        else:
            self.daily_stats['losing_trades'] += 1
            self.consecutive_losses += 1

        self.journal.record_order(slug, pos['side'], price, pos['size'], 'SELL', pnl=net_pnl)
        print(f"Exited {slug} {pos['side']} @ {price:.3f}, PnL: {net_pnl:.3f}")

        # Check for consecutive loss pause
        if self.consecutive_losses >= self.CONSECUTIVE_LOSS_LIMIT:
            self.paused = True
            print(f"Auto‑paused after {self.consecutive_losses} consecutive losses.")

    # Other existing methods (like get_today_summary, etc.) should remain unchanged.
    # If you have them in your original trader.py, add them here.
