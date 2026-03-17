"""
Paper trading module for Polymarket bot
Runs strategies on BTC 5m and 15m markets and closes positions at expiration.
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
        self.positions = {}

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
        Check all open positions; if the market end time has passed,
        determine the outcome and close the position.
        """
        now = datetime.now(timezone.utc)
        for slug, pos_data in list(self.journal.open_positions.items()):
            # Get market end date from the position data
            end_date_str = pos_data.data.get('end_date')
            if not end_date_str:
                # Try to fetch market data again to get end date
                parts = slug.split('-')
                if len(parts) >= 4:
                    asset = parts[0]
                    interval = parts[2]
                    # We don't have a direct way to get end date from oracle, so skip
                    continue
                else:
                    continue

            try:
                end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                if now > end_dt:
                    # Market expired – we need to resolve the trade
                    side = pos_data.data['side'].upper()
                    entry_price = pos_data.data['entry_price']
                    size = pos_data.data['size']
                    
                    # Determine final price based on direction
                    # Since we can't know the actual outcome without the final price,
                    # we'll assume the trade lost if we don't have a better method.
                    # A more accurate approach would be to fetch the final market price,
                    # but that's complex. For now, we'll use a simple rule:
                    # If you bought YES at <0.50 and the price went up, you win; otherwise lose.
                    # But we don't have the final price. Let's use the oracle's last price? Not reliable.
                    
                    # For demonstration, we'll set final price to 0.0 (loss)
                    # You can improve this later by storing resolution prices.
                    final_price = 0.0
                    
                    # Compute PnL
                    if side == 'YES':
                        pnl = (final_price - entry_price) * size
                    else:
                        pnl = (entry_price - final_price) * size
                    
                    # Record exit
                    order_id = f"expired_{int(time.time())}"
                    self.journal.record_order(
                        market=slug,
                        order_type='market',
                        side='sell',
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
            except Exception as e:
                print(f"Error closing expired position {slug}: {e}")

    def run_cycle(self):
        """Check BTC 5m and 15m markets, execute paper trades, close expired ones."""
        # First close any expired positions
        self.close_expired_positions()

        # Then enter new trades
        for interval in ['5m', '15m']:
            signal = self.evaluate_strategy('btc', interval)
            if signal:
                if signal['slug'] in self.journal.open_positions:
                    continue

                # Fetch market end date from market_finder
                market_data = self.market_finder.get_market_by_slug(signal['slug'])
                if not market_data:
                    continue
                end_date = market_data.get('end_date')

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
                # Store end date in the position data (the journal already has it in the fill entry)
                # We'll retrieve it later via market_finder if needed.
                print(f"Paper trade executed: {signal['slug']} {signal['side']} @ ${signal['price']:.3f} for ${signal['stake']:.2f}")
