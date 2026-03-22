"""
Order book simulation for Polymarket.
"""

import requests
import time
from typing import Dict, Tuple, Optional

# Cache for token IDs to avoid repeated lookups
_token_id_cache = {}

def get_token_id_from_slug(slug: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Given a market slug (e.g., 'btc-updown-5m-1234567890'), fetch the YES and NO token IDs.
    Uses the Polymarket Gamma API.
    """
    if slug in _token_id_cache:
        return _token_id_cache[slug]

    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                market = data[0]
                # The 'clob_token_ids' field is a list: [yes_token_id, no_token_id]
                tokens = market.get('clob_token_ids', [])
                if len(tokens) >= 2:
                    yes_token = tokens[0]
                    no_token = tokens[1]
                    _token_id_cache[slug] = (yes_token, no_token)
                    return yes_token, no_token
    except Exception as e:
        print(f"Error fetching token IDs for {slug}: {e}")
    _token_id_cache[slug] = (None, None)
    return None, None

def get_order_book(token_id: str) -> Dict:
    """
    Fetch the order book for a specific token.
    Returns a dict with 'bids' and 'asks', each a list of [price, size].
    """
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    try:
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching order book: {e}")
    return {'bids': [], 'asks': []}

def simulate_market_order(token_id: str, side: str, stake: float) -> Tuple[float, float]:
    """
    Simulate a market order for a given token.
    side: 'buy' or 'sell'
    stake: amount of USDC to spend (for buy) or number of shares to sell (for sell)
    Returns (average_price, filled_stake)
        - For buy: average price per share, and total stake spent (should equal input stake)
        - For sell: average price per share, and total stake received (actual USDC)
    """
    book = get_order_book(token_id)
    if side == 'buy':
        orders = book.get('asks', [])
        if not orders:
            return 0.0, 0.0
        remaining = stake
        total_cost = 0.0
        total_shares = 0.0
        for price_str, size_str in orders:
            price = float(price_str)
            size = float(size_str)
            cost = price * size
            if cost <= remaining:
                # Take whole level
                total_cost += cost
                total_shares += size
                remaining -= cost
            else:
                # Partial fill
                shares = remaining / price
                total_cost += remaining
                total_shares += shares
                remaining = 0
                break
        if total_shares == 0:
            return 0.0, 0.0
        avg_price = total_cost / total_shares
        return avg_price, stake  # stake fully used
    else:  # sell
        orders = book.get('bids', [])
        if not orders:
            return 0.0, 0.0
        remaining = stake  # number of shares to sell
        total_received = 0.0
        total_shares = 0.0
        for price_str, size_str in orders:
            price = float(price_str)
            size = float(size_str)
            if size <= remaining:
                total_received += price * size
                total_shares += size
                remaining -= size
            else:
                total_received += price * remaining
                total_shares += remaining
                remaining = 0
                break
        if total_shares == 0:
            return 0.0, 0.0
        avg_price = total_received / total_shares
        return avg_price, total_received
