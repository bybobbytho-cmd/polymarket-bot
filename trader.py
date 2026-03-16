"""
Paper trading module for Polymarket bot
Runs strategies on BTC 5m and 15m markets.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from config import MinuteMarketFinder
from journal import PolymarketJournal

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, oracle_url: str, capital: float):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.capital = capital
        self.positions = {}

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
        """Trades BTC only (both 5m and 15m)."""
        if asset != 'btc':
            return None
        up, down, slug = self.fetch_price(asset, interval)
        if up is None or down is None:
            return None

        stake = max(1.0, self.capital * 0.02)  # $1 minimum

        if up < 0.20:
            return {
                'side': 'YES',
                'price': up,
                'slug': slug,
                'stake': stake,
                'confidence': 0.6,
                'asset': asset,
                'interval': interval
            }
        elif up > 0.80:
            return {
                'side': 'NO',
                'price': down,
                'slug': slug,
                'stake': stake,
                'confidence': 0.6,
                'asset': asset,
                'interval': interval
            }
        return None

    def close_expired_positions(self):
        """Close positions whose market end time has passed."""
        now = datetime.now(timezone.utc)
        for slug, pos_data in list(self.journal.open_positions.items()):
            end_date_str = pos_data.data.get('end_date')
            if end_date_str:
                try:
                    end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    if now > end_dt:
                        # Market expired – assume trade loses (simplified)
                        print(f"Auto-closing expired position {slug}")
                        order_id = f"expired_{int(time.time())}"
                        self.journal.record_order(
                            market=slug,
                            order_type='market',
                            side='sell',
                            price=0.0,
                            size=pos_data.data['size']
                        )
                        self.journal.record_fill(
                            market=slug,
                            side='sell',
                            price=0.0,
                            size=pos_data.data['size'],
                            order_id=order_id,
                            fee=0.0
                        )
                except Exception as e:
                    print(f"Error closing expired position {slug}: {e}")

    def run_cycle(self):
        """Check BTC 5m and 15m markets, execute paper trades, close expired ones."""
        self.close_expired_positions()

        for interval in ['5m', '15m']:
            signal = self.evaluate_strategy('btc', interval)
            if signal:
                if signal['slug'] in self.journal.open_positions:
                    continue

                self.journal.record_signal(
                    market=signal['slug'],
                    price=signal['price'],
                    confidence=signal['confidence'],
                    action=signal['side']
                )
                order_id = f"paper_{int(time.time())}"
                self.journal.record_order(
                    market=signal['slug'],
                    order_type='limit',
                    side=signal['side'],
                    price=signal['price'],
                    size=signal['stake']
                )
                self.journal.record_fill(
                    market=signal['slug'],
                    side=signal['side'],
                    price=signal['price'],
                    size=signal['stake'],
                    order_id=order_id,
                    fee=0.0
                )
                print(f"Paper trade executed: {signal['slug']} {signal['side']} @ ${signal['price']:.3f} for ${signal['stake']:.2f}")
