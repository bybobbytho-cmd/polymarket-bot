"""
Paper Trader – Advisory with detailed signal storage.
"""

import os
import time
import requests
from typing import Optional

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
        self.positions = {}
        self.paused = False
        self.consecutive_losses = 0
        self.daily_stats = {'realized_pnl': 0.0, 'orders_filled': 0,
                            'winning_trades': 0, 'losing_trades': 0}
        
        # Advisory parameters
        self.MIN_EDGE = 0.005  # 0.5% edge (for testing)
        self.external = ExternalSignals()
        self.signals = {}          # market_slug -> signal dict
        self.last_sent_signal = {} # slug -> timestamp

    # Compatibility stubs
    def fetch_price_from_oracle(self, asset, interval):
        return None, None, None
    def get_market_price(self, slug, side, action):
        return 0.0
    def _enter_position(self, slug, side, price, size):
        pass
    def _exit_position(self, slug, price, profit):
        pass

    def run_cycle(self):
        if self.paused:
            return

        now = int(time.time())
        for market_base in ['btc-updown-5m', 'btc-updown-15m']:
            period = 300 if market_base.endswith('5m') else 900
            window_start = now - (now % period)
            slug = f"{market_base}-{window_start}"
            market_data = self.market_finder.get_market_by_slug(slug)
            if not market_data:
                continue

            # Get ask price for YES
            yes_token, _ = get_token_id_from_slug(slug)
            if not yes_token:
                continue
            book = get_order_book(yes_token)
            if not book.get('asks'):
                continue
            ask_price = float(book['asks'][0][0])

            # Fetch external signals
            futures_change = self.external.get_cme_futures_change()
            binance_imbalance = self.external.get_binance_btc_orderbook_imbalance()
            news_sentiment = self.external.get_news_sentiment()

            # Compute fair value (same as before)
            futures_score = 0.5 + 10 * (futures_change if futures_change is not None else 0.0)
            futures_score = max(0.0, min(1.0, futures_score))
            imbalance_score = ((binance_imbalance if binance_imbalance is not None else 0.0) + 1) / 2
            sentiment_score = ((news_sentiment if news_sentiment is not None else 0.0) + 1) / 2
            fair_value = 0.4 * futures_score + 0.4 * imbalance_score + 0.2 * sentiment_score

            # Edge
            edge = (fair_value - ask_price) / ask_price if ask_price > 0 else 0
            actionable = edge > self.MIN_EDGE
            side = 'YES' if actionable else None

            self.signals[slug] = {
                'timestamp': now,
                'side': side,
                'ask_price': ask_price,
                'fair_value': fair_value,
                'edge': edge,
                'actionable': actionable,
                'futures_change': futures_change if futures_change is not None else 0.0,
                'binance_imbalance': binance_imbalance if binance_imbalance is not None else 0.0,
                'news_sentiment': news_sentiment if news_sentiment is not None else 0.0,
            }
            print(f"Signal for {slug}: edge={edge:.2%}, actionable={actionable}")

    def get_signal(self, asset='btc', interval='5m'):
        now = int(time.time())
        period = 300 if interval == '5m' else 900
        window_start = now - (now % period)
        slug = f"{asset}-updown-{interval}-{window_start}"
        return self.signals.get(slug)

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
