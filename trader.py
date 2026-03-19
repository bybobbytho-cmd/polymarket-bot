"""
Paper trading module for Polymarket bot
Runs strategies on BTC 5m and 15m markets and closes positions at expiration.
Uses its own position list for reliability.
"""

import time
import requests
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
        self.positions = {}  # slug -> {side, entry_price, size, start_time, interval}

    def fetch_price(self, asset: str, interval: str):
        """Get current price and slug from oracle."""
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
        """
        Check all open positions stored in self.positions;
        if the market end time has passed, close the position (assume loss for now).
        """
        now = datetime.now(timezone.utc)
        print(f"Checking for expired positions at {now.isoformat()}")
        slugs_to_remove = []
        for slug, pos in self.positions.items():
            # Parse start time from slug
            try:
                parts = slug.split('-')
                if len(parts) < 4:
                    continue
                timestamp_str = parts[3]
                start_time = datetime.fromtimestamp(int(timestamp_str), tz=timezone.utc)
                interval = parts[2]  # '5m' or '15m'
                if interval == '5m':
                    duration = timedelta(minutes=5)
                elif interval == '15m':
                    duration = timedelta(minutes=15)
                else:
                    continue
                end_time = start_time + duration
                if now > end_time:
                    # Market expired – close as loss
                    entry_price = pos['entry_price']
                    size = pos['size']
                    side = pos['side']
                    final_price = 0.0  # assume loss
                    # Compute PnL
                    if side == 'YES':
                        pnl = (final_price - entry_price) * size
                    else:
                        pnl = (entry_price - final_price) * size

                    # Record exit in journal
                    order_id = f"expired_{int(time.time())}"
                    self.journal.record_order(
                        market=slug,
                        order_type='market',
                        side='sell',  # closing side is always sell
                        price=final_price,
                        size=size
                    )
                    self.journal.record_fill(
                        market=slug,
                        side='sell',
                        price=final_price,
                        size=size,
                        order_id=order_id,
                        fee=0.0
                    )
                    print(f"Closed expired position {slug} with PnL ${pnl:.2f}")
                    slugs_to_remove.append(slug)
            except Exception as e:
                print(f"Error closing expired position {slug}: {e}")

        for slug in slugs_to_remove:
            del self.positions[slug]

    def run_cycle(self):
        """Check BTC 5m and 15m markets, execute paper trades, close expired ones."""
        # First close any expired positions
        self.close_expired_positions()

        # Then enter new trades
        for interval in ['5m', '15m']:
            signal = self.evaluate_strategy('btc', interval)
            if signal:
                if signal['slug'] in self.positions:
                    continue

                # Record signal and order (journal)
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
                    side=signal['side'],  # 'YES' or 'NO'
                    price=signal['price'],
                    size=signal['stake']
                )
                # Record fill with side='buy' for position (journal uses 'buy'/'sell')
                self.journal.record_fill(
                    market=signal['slug'],
                    side='buy',  # we are buying a contract
                    price=signal['price'],
                    size=signal['stake'],
                    order_id=order_id,
                    fee=0.0
                )
                # Add to our own position list
                self.positions[signal['slug']] = {
                    'side': signal['side'],
                    'entry_price': signal['price'],
                    'size': signal['stake'],
                    'start_time': signal['slug'].split('-')[-1],  # store timestamp for later
                    'interval': interval
                }
                print(f"Paper trade executed: {signal['slug']} {signal['side']} @ ${signal['price']:.3f} for ${signal['stake']:.2f}")
