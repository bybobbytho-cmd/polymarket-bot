"""
Paper Trader for Polymarket – Advisory version (no auto‑trading).
Stores signals for each market so Telegram can query them.
"""

import os
import time
import requests
from datetime import datetime
from typing import Dict, Optional, Tuple

from config import MinuteMarketFinder, Config
from journal import PolymarketJournal
from orderbook import get_token_id_from_slug, get_order_book
from external_signals import ExternalSignals

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, 
                 oracle_url: str = None, capital: float = 10.0):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.capital = capital
        self.peak_capital = capital
        self.positions = {}          # not used, but kept for compatibility
        self.paused = False
        self.consecutive_losses = 0
        self.daily_stats = {'realized_pnl': 0.0, 'orders_filled': 0,
                            'winning_trades': 0, 'losing_trades': 0}
        
        # Strategy parameters
        self.ENTRY_THRESHOLD = 0.20
        self.TAKE_PROFIT_PCT = 0.10
        self.STOP_LOSS_PCT = 0.20
        self.CONSECUTIVE_LOSS_LIMIT = 3
        self.DAILY_LOSS_LIMIT = 5.0
        self.USE_ORDERBOOK = True
        self.FEE_PCT = 0.01
        
        # Advisory specific
        self.external = ExternalSignals()
        self.signals = {}          # market_slug -> {'side', 'ask_price', 'fair_value', 'edge', 'actionable', 'timestamp'}
        self.last_sent_signal = {} # market_slug -> timestamp of last sent alert

    # ---------- Compatibility stubs ----------
    def fetch_price_from_oracle(self, asset, interval):
        return None, None, None

    def get_market_price(self, slug, side, action):
        return 0.0

    def _enter_position(self, slug, side, price, size):
        pass

    def _exit_position(self, slug, price, profit):
        pass

    # ---------- Main cycle: update signals for all markets ----------
    def run_cycle(self):
        if self.paused:
            return

        if self.daily_stats['realized_pnl'] <= -self.DAILY_LOSS_LIMIT:
            print(f"Daily loss limit reached. Pausing.")
            self.paused = True
            return

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

            # Get Polymarket ask price for YES from order book
            yes_token, no_token = get_token_id_from_slug(slug)
            if not yes_token:
                continue
            book = get_order_book(yes_token)
            if not book.get('asks'):
                continue
            ask_price = float(book['asks'][0][0])

            # Get fair value from external signals
            fair_value = self.external.get_fair_value_yes()

            # Calculate edge
            if ask_price > 0:
                edge = (fair_value - ask_price) / ask_price
            else:
                edge = 0

            MIN_EDGE = 0.02  # 2% threshold

            # Determine recommended side
            if edge > MIN_EDGE:
                side = 'YES'
                actionable = True
            else:
                # Also check if buying NO could have edge (1 - fair_value vs NO ask)
                # For simplicity, we only trade YES in this version.
                side = None
                actionable = False

            # Store signal
            self.signals[slug] = {
                'timestamp': now,
                'side': side,
                'ask_price': ask_price,
                'fair_value': fair_value,
                'edge': edge,
                'actionable': actionable
            }
            print(f"Signal updated for {slug}: side={side}, edge={edge:.2%}")

    # ---------- Method to get signal for a specific market (by slug or by asset/interval) ----------
    def get_signal(self, asset='btc', interval='5m'):
        """Return the latest signal for the current market window."""
        now = int(time.time())
        period = 300 if interval == '5m' else 900
        window_start = now - (now % period)
        slug = f"{asset}-updown-{interval}-{window_start}"
        signal = self.signals.get(slug)
        if not signal:
            return None
        return signal

    # ---------- Other methods (pause, resume, etc.) ----------
    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.consecutive_losses = 0

    def get_status(self):
        return {
            'capital': self.capital,
            'peak_capital': self.peak_capital,
            'paused': self.paused,
            'consecutive_losses': self.consecutive_losses,
            'daily_stats': self.daily_stats,
            'journal_summary': self.journal.get_today_summary()
        }
