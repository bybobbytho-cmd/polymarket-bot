"""
Paper trading module for Polymarket bot
Runs strategies and logs paper trades via the journal.
"""

import time
from datetime import datetime
from typing import Dict, List, Tuple

from config import MinuteMarketFinder
from journal import PolymarketJournal

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, oracle_url: str):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.positions = {}  # track open paper positions by slug

    def fetch_price(self, asset: str, interval: str) -> Tuple[float, float, str]:
        """Get current price and slug from oracle."""
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

    def evaluate_strategy(self, asset: str, interval: str) -> Dict:
        """
        Simple mean-reversion strategy.
        Returns signal dict with side and confidence, or None.
        """
        up, down, slug = self.fetch_price(asset, interval)
        if up is None or down is None:
            return None

        # Example: if price is below 0.20, consider buying
        if up < 0.20:
            return {
                'side': 'YES',
                'price': up,
                'slug': slug,
                'confidence': 0.6,
                'size_pct': 0.02  # 2% of capital
            }
        elif up > 0.80:
            return {
                'side': 'NO',
                'price': down,
                'slug': slug,
                'confidence': 0.6,
                'size_pct': 0.02
            }
        return None

    def run_cycle(self):
        """Check all minute markets and execute paper trades."""
        for asset in ['btc', 'eth']:
            for interval in ['5m', '15m']:
                signal = self.evaluate_strategy(asset, interval)
                if signal:
                    # Check if we already have a position in this market
                    if signal['slug'] in self.positions:
                        continue  # avoid double entry

                    # Record a paper trade via journal
                    self.journal.record_signal(
                        market=signal['slug'],
                        price=signal['price'],
                        confidence=signal['confidence'],
                        action=signal['side']
                    )
                    # Simulate an order and fill
                    order_id = f"paper_{int(time.time())}"
                    self.journal.record_order(
                        market=signal['slug'],
                        order_type='limit',
                        side=signal['side'],
                        price=signal['price'],
                        size=signal['size_pct']  # will need capital later
                    )
                    self.journal.record_fill(
                        market=signal['slug'],
                        side=signal['side'],
                        price=signal['price'],
                        size=signal['size_pct'],
                        order_id=order_id,
                        fee=0.0
                    )
                    # Track open position
                    self.positions[signal['slug']] = {
                        'side': signal['side'],
                        'entry_price': signal['price'],
                        'size': signal['size_pct'],
                        'entry_time': datetime.utcnow().isoformat()
                    }
                    print(f"Paper trade executed: {signal['slug']} {signal['side']} @ {signal['price']}")

        # In a real implementation, you'd also check for exit conditions
        # For now, we'll just log entries.
