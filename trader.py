"""
Paper trading module for Polymarket bot
Runs strategies and logs paper trades via the journal.
Stake is computed in dollars with a $1 minimum.
"""

import time
from datetime import datetime
from typing import Dict, Optional

from config import MinuteMarketFinder
from journal import PolymarketJournal

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, oracle_url: str, capital: float):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.capital = capital          # virtual capital in dollars
        self.positions = {}              # track open paper positions by slug

    def fetch_price(self, asset: str, interval: str):
        import requests
        try:
            url = f"{self.oracle_url}/api/price/{asset}/{interval}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('up'), data.get('down'), data.get('slug')
        except Exception as e:
            print(f"Oracle error in trader: {e}")
        return None, None, None

    def evaluate_strategy(self, asset: str, interval: str) -> Optional[Dict]:
        """
        Simple mean-reversion strategy.
        Returns signal dict with side, price, slug, and stake (in dollars).
        """
        up, down, slug = self.fetch_price(asset, interval)
        if up is None or down is None:
            return None

        # Determine stake: at least $1, and not more than 2% of capital (capped at 2% for risk)
        stake = max(1.0, self.capital * 0.02)

        if up < 0.20:
            return {
                'side': 'YES',
                'price': up,
                'slug': slug,
                'stake': stake,
                'confidence': 0.6
            }
        elif up > 0.80:
            return {
                'side': 'NO',
                'price': down,
                'slug': slug,
                'stake': stake,
                'confidence': 0.6
            }
        return None

    def run_cycle(self):
        """Check all minute markets and execute paper trades."""
        for asset in ['btc', 'eth']:
            for interval in ['5m', '15m']:
                signal = self.evaluate_strategy(asset, interval)
                if signal:
                    if signal['slug'] in self.positions:
                        continue  # avoid double entry

                    # Record signal
                    self.journal.record_signal(
                        market=signal['slug'],
                        price=signal['price'],
                        confidence=signal['confidence'],
                        action=signal['side']
                    )
                    # Simulate order and fill
                    order_id = f"paper_{int(time.time())}"
                    self.journal.record_order(
                        market=signal['slug'],
                        order_type='limit',
                        side=signal['side'],
                        price=signal['price'],
                        size=signal['stake']           # store as dollar amount
                    )
                    self.journal.record_fill(
                        market=signal['slug'],
                        side=signal['side'],
                        price=signal['price'],
                        size=signal['stake'],
                        order_id=order_id,
                        fee=0.0
                    )
                    # Track open position
                    self.positions[signal['slug']] = {
                        'side': signal['side'],
                        'entry_price': signal['price'],
                        'size': signal['stake'],
                        'entry_time': datetime.utcnow().isoformat()
                    }
                    print(f"Paper trade executed: {signal['slug']} {signal['side']} @ ${signal['price']:.3f} for ${signal['stake']:.2f}")
