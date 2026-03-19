"""
Paper trading module with pause on consecutive losses and daily loss limit.
"""

import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from config import MinuteMarketFinder
from journal import PolymarketJournal

# ==================== CONFIGURABLE PARAMETERS ====================
ENTRY_THRESHOLD = 0.20      # Buy YES when price < this; buy NO when price > (1 - ENTRY_THRESHOLD)
TAKE_PROFIT_PCT = 0.10      # Sell if profit >= 10%
STOP_LOSS_PCT = 0.30        # Sell if loss >= 30%
CONSECUTIVE_LOSS_LIMIT = 3  # Pause after this many losses in a row
DAILY_LOSS_LIMIT = 0.50     # Pause if realized loss for the day exceeds $0.50
# ================================================================

class PaperTrader:
    def __init__(self, journal: PolymarketJournal, market_finder: MinuteMarketFinder, oracle_url: str, capital: float):
        self.journal = journal
        self.market_finder = market_finder
        self.oracle_url = oracle_url
        self.capital = capital
        self.positions = {}          # slug -> position dict
        self.consecutive_losses = 0
        self.paused = False
        self.peak_capital = capital

    def fetch_price(self, asset: str, interval: str):
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
        if asset != 'btc' or self.paused:
            return None
        up, down, slug = self.fetch_price(asset, interval)
        if up is None or down is None:
            return None
        stake = max(1.0, self.capital * 0.02)  # $1 minimum
        if up < ENTRY_THRESHOLD:
            return {
                'side': 'YES',
                'price': up,
                'slug': slug,
                'stake': stake,
                'confidence': 0.6,
                'asset': asset,
                'interval': interval
            }
        elif up > (1 - ENTRY_THRESHOLD):
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

    def check_exit_conditions(self):
        slugs_to_remove = []
        for slug, pos in self.positions.items():
            asset = 'btc'
            interval = pos['interval']
            up, down, _ = self.fetch_price(asset, interval)
            if up is None or down is None:
                continue
            current_price = up if pos['side'] == 'YES' else down
            entry_price = pos['entry_price']
            size = pos['size']
            if pos['side'] == 'YES':
                profit_pct = (current_price - entry_price) / entry_price
            else:
                profit_pct = (entry_price - current_price) / entry_price

            if profit_pct >= TAKE_PROFIT_PCT:
                final_price = current_price
                print(f"Take profit on {slug} at {final_price:.3f} (entry {entry_price:.3f})")
            elif profit_pct <= -STOP_LOSS_PCT:
                final_price = current_price
                print(f"Stop loss on {slug} at {final_price:.3f} (entry {entry_price:.3f})")
            else:
                continue

            if pos['side'] == 'YES':
                pnl = (final_price - entry_price) * size
            else:
                pnl = (entry_price - final_price) * size

            order_id = f"exit_{int(time.time())}"
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
            slugs_to_remove.append(slug)

            # Update consecutive losses
            if pnl < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0

            # Update capital
            self.capital += pnl
            if self.capital > self.peak_capital:
                self.peak_capital = self.capital

        for slug in slugs_to_remove:
            del self.positions[slug]

    def close_expired_positions(self):
        now = datetime.now(timezone.utc)
        slugs_to_remove = []
        for slug, pos in self.positions.items():
            try:
                parts = slug.split('-')
                if len(parts) < 4:
                    continue
                timestamp_str = parts[3]
                start_time = datetime.fromtimestamp(int(timestamp_str), tz=timezone.utc)
                interval = parts[2]
                if interval == '5m':
                    duration = timedelta(minutes=5)
                elif interval == '15m':
                    duration = timedelta(minutes=15)
                else:
                    continue
                end_time = start_time + duration
                if now > end_time:
                    entry_price = pos['entry_price']
                    size = pos['size']
                    side = pos['side']
                    final_price = 0.0  # assume loss
                    if side == 'YES':
                        pnl = (final_price - entry_price) * size
                    else:
                        pnl = (entry_price - final_price) * size
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
                    slugs_to_remove.append(slug)

                    # Update consecutive losses and capital
                    if pnl < 0:
                        self.consecutive_losses += 1
                    else:
                        self.consecutive_losses = 0
                    self.capital += pnl
                    if self.capital > self.peak_capital:
                        self.peak_capital = self.capital
            except Exception as e:
                print(f"Error closing expired {slug}: {e}")

        for slug in slugs_to_remove:
            del self.positions[slug]

    def run_cycle(self):
        """Main cycle: check exits, expired, then enter new trades if not paused."""
        self.check_exit_conditions()
        self.close_expired_positions()

        # Auto‑pause if daily loss limit exceeded
        daily_realized = self.journal.daily_stats['realized_pnl']
        if daily_realized <= -DAILY_LOSS_LIMIT:
            self.paused = True
            print(f"Daily loss limit reached (${daily_realized:.2f}). Bot paused.")

        # Auto‑pause if consecutive losses limit reached
        if self.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
            self.paused = True
            print(f"Consecutive losses ({self.consecutive_losses}) reached. Bot paused.")

        if self.paused:
            return  # don't enter new trades

        for interval in ['5m', '15m']:
            signal = self.evaluate_strategy('btc', interval)
            if signal and signal['slug'] not in self.positions:
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
                    side='buy',
                    price=signal['price'],
                    size=signal['stake'],
                    order_id=order_id,
                    fee=0.0
                )
                self.positions[signal['slug']] = {
                    'side': signal['side'],
                    'entry_price': signal['price'],
                    'size': signal['stake'],
                    'interval': interval
                }
                print(f"Paper trade executed: {signal['slug']} {signal['side']} @ ${signal['price']:.3f} for ${signal['stake']:.2f}")
