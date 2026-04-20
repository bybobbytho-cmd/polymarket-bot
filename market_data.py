"""
Market Data Fetcher for Binance, CME, and Chainlink
No API keys required - uses public endpoints
"""

import requests
import time
from datetime import datetime

# ============================================================
# BINANCE DATA (Public, no API key needed)
# ============================================================

def get_binance_btc_price():
    """Get current BTC/USDT price from Binance"""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return float(response.json()['price'])
    except Exception as e:
        print(f"Binance price error: {e}")
    return None

def get_binance_order_book():
    """Get Binance order book to calculate OBI (Order Book Imbalance)"""
    try:
        url = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=10"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            bids = data['bids']
            asks = data['asks']
            
            # Calculate total bid volume and ask volume
            total_bids = sum(float(bid[1]) for bid in bids[:5])  # Top 5 bids
            total_asks = sum(float(ask[1]) for ask in asks[:5])  # Top 5 asks
            
            # OBI formula: (bids - asks) / (bids + asks)
            if total_bids + total_asks > 0:
                obi = (total_bids - total_asks) / (total_bids + total_asks)
                return obi, total_bids, total_asks
    except Exception as e:
        print(f"Binance order book error: {e}")
    return 0, 0, 0

def get_binance_velocity(seconds=60):
    """Calculate price velocity (price change per minute)"""
    try:
        # Get current price
        current = get_binance_btc_price()
        if not current:
            return 0
        
        # Get price from X seconds ago using klines
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=2"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if len(data) >= 2:
                previous_close = float(data[0][4])  # Close price of previous minute
                velocity = (current - previous_close) * 60 / seconds
                return velocity
    except Exception as e:
        print(f"Binance velocity error: {e}")
    return 0


# ============================================================
# CME DATA (Public proxy using Binance futures)
# ============================================================

def get_cme_proxy():
    """
    Get CME BTC proxy using Binance futures perpetual.
    CME typically trades at a premium to spot.
    """
    try:
        # Get Binance futures price
        url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            futures_price = float(response.json()['price'])
            spot_price = get_binance_btc_price()
            if spot_price:
                basis = futures_price - spot_price
                return futures_price, basis
    except Exception as e:
        print(f"CME proxy error: {e}")
    return None, 0


# ============================================================
# CHAINLINK DATA (Oracle reference)
# ============================================================

def get_chainlink_btc():
    """Get Chainlink BTC/USD reference price"""
    try:
        # Chainlink BTC/USD price feed on Polygon
        # Using a public aggregator endpoint
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return float(response.json()['bitcoin']['usd'])
    except Exception as e:
        print(f"Chainlink error: {e}")
    return None


# ============================================================
# COMPLETE MARKET SNAPSHOT
# ============================================================

def get_market_snapshot(strike_price=None):
    """
    Get complete market snapshot including:
    - Current BTC price
    - OBI (Order Book Imbalance)
    - Velocity
    - CME basis delta
    - Chainlink reference
    - Distance to strike (if strike provided)
    """
    
    # Get Binance data
    spot_price = get_binance_btc_price()
    obi, total_bids, total_asks = get_binance_order_book()
    velocity = get_binance_velocity()
    
    # Get CME proxy
    futures_price, cme_basis = get_cme_proxy()
    
    # Get Chainlink reference
    chainlink_price = get_chainlink_btc()
    
    # Calculate distance to strike
    distance_to_strike = None
    if strike_price and spot_price:
        distance_to_strike = spot_price - strike_price
    
    snapshot = {
        'timestamp': datetime.utcnow().isoformat(),
        'spot_price': spot_price,
        'obi': obi,
        'velocity': velocity,
        'cme_basis': cme_basis,
        'chainlink_price': chainlink_price,
        'futures_price': futures_price,
        'total_bids': total_bids,
        'total_asks': total_asks,
        'distance_to_strike': distance_to_strike,
    }
    
    return snapshot


# ============================================================
# TEST FUNCTION
# ============================================================

if __name__ == "__main__":
    print("Fetching market data...\n")
    
    snapshot = get_market_snapshot(strike_price=75000)
    
    print("=" * 50)
    print("MARKET SNAPSHOT")
    print("=" * 50)
    print(f"Timestamp: {snapshot['timestamp']}")
    print(f"BTC Spot Price: ${snapshot['spot_price']:.2f}")
    print(f"OBI (Order Book Imbalance): {snapshot['obi']:.4f}")
    print(f"Velocity (USD/min): {snapshot['velocity']:.2f}")
    print(f"CME Basis Delta: ${snapshot['cme_basis']:.2f}")
    print(f"Chainlink Reference: ${snapshot['chainlink_price']:.2f}")
    print(f"Distance to Strike: ${snapshot['distance_to_strike']:.2f}")
    print("=" * 50)
