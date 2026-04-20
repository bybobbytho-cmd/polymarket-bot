"""
Market Intelligence Report Generator
Combines Polymarket data with Binance/CME data to generate trading signals
"""

import requests
import json
from datetime import datetime
from market_data import get_market_snapshot
from regime import detect_regime
from executor import should_execute

# Polymarket API base
POLYMARKET_API = "https://gamma-api.polymarket.com"

def get_polymarket_prices(market_slug):
    """Get current UP/DOWN prices from Polymarket"""
    url = f"{POLYMARKET_API}/events?slug={market_slug}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200 and response.json():
            event = response.json()[0]
            if event.get('markets') and len(event['markets']) > 0:
                market = event['markets'][0]
                prices = market.get('outcomePrices')
                if prices:
                    # Handle string prices like '["1", "0"]' or list format
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    if len(prices) >= 2:
                        return float(prices[0]), float(prices[1])  # UP, DOWN
    except Exception as e:
        print(f"Error fetching Polymarket prices: {e}")
    return None, None

def get_rsi_1h():
    """
    Calculate 1-hour RSI for BTC using Binance data
    Simplified version - returns neutral if can't calculate
    """
    try:
        # Fetch last 14 hourly candles
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=14"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            closes = [float(candle[4]) for candle in data]
            
            # Calculate RSI
            gains = []
            losses = []
            for i in range(1, len(closes)):
                change = closes[i] - closes[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses)
            
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
    except Exception as e:
        print(f"RSI calculation error: {e}")
    
    return 50.0  # Neutral fallback

def generate_report(market_slug, strike_price):
    """
    Generate complete Market Intelligence Report
    """
    print("\n" + "="*60)
    print("MARKET INTELLIGENCE REPORT")
    print("="*60)
    print(f"Slug: {market_slug}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print("-"*60)
    
    # Get Polymarket prices
    up_price, down_price = get_polymarket_prices(market_slug)
    if up_price and down_price:
        print(f"\n📊 POLYMARKET PRICES:")
        print(f"   UP: {up_price:.3f} ({up_price*100:.1f}%)")
        print(f"   DOWN: {down_price:.3f} ({down_price*100:.1f}%)")
        crowd_direction = "UP" if up_price > down_price else "DOWN"
        crowd_conviction = max(up_price, down_price)
        print(f"   Crowd Direction: {crowd_direction} ({crowd_conviction*100:.0f}% conviction)")
    else:
        print(f"\n📊 POLYMARKET PRICES: Unable to fetch")
    
    # Get market data (Binance, CME, Chainlink)
    snapshot = get_market_snapshot(strike_price=strike_price)
    
    print(f"\n📈 MARKET DATA:")
    if snapshot['spot_price']:
        print(f"   BTC Spot Price: ${snapshot['spot_price']:.2f}")
    else:
        print(f"   BTC Spot Price: N/A")
    print(f"   OBI (Whale Imbalance): {snapshot['obi']:.4f}")
    print(f"   Velocity (USD/min): {snapshot['velocity']:.2f}")
    print(f"   CME Basis Delta: ${snapshot['cme_basis']:.2f}")
    if snapshot['chainlink_price']:
        print(f"   Chainlink Oracle: ${snapshot['chainlink_price']:.2f}")
    if snapshot['distance_to_strike']:
        print(f"   Distance to Strike: ${snapshot['distance_to_strike']:.2f}")
    
    # Get RSI
    rsi = get_rsi_1h()
    print(f"   1H RSI: {rsi:.1f}")
    
    # Calculate absolute distance for regime detection
    distance_abs = abs(snapshot['distance_to_strike']) if snapshot['distance_to_strike'] else 999
    
    # Regime detection
    regime, trade_dir, confidence, regime_reason = detect_regime(
        obi=snapshot['obi'],
        cme_delta=snapshot['cme_basis'],
        distance_to_strike=distance_abs,
        velocity=snapshot['velocity'],
        rsi_1h=rsi
    )
    
    print(f"\n🎯 REGIME DETECTION:")
    print(f"   Regime: {regime}")
    print(f"   Reason: {regime_reason}")
    print(f"   Confidence: {confidence}%")
    
    # Execution decision
    price_position = snapshot['distance_to_strike'] if snapshot['distance_to_strike'] else 0
    
    execute, direction, size_mult, exec_reason = should_execute(
        regime=regime,
        trade_direction=trade_dir,
        price_position=price_position,
        distance_to_strike=distance_abs,
        confidence=confidence
    )
    
    print(f"\n⚡ EXECUTION DECISION:")
    if execute and direction:
        print(f"   ✅ VERDICT: EXECUTE {direction}")
        print(f"   Size: {int(size_mult*100)}% of normal position")
        print(f"   Reason: {exec_reason}")
    else:
        print(f"   ❌ VERDICT: PASS")
        print(f"   Reason: {exec_reason}")
    
    print("\n" + "="*60)
    
    return {
        'verdict': f"EXECUTE_{direction}" if execute and direction else "PASS",
        'regime': regime,
        'confidence': confidence,
        'reason': exec_reason
    }


if __name__ == "__main__":
    # Example: analyze current BTC 5m market
    from config import BTCMarketFinder
    
    finder = BTCMarketFinder()
    markets = finder.discover_btc_markets()
    
    if markets:
        for key, market_data in markets.items():
            if key == "BTC_5m":
                # Use current spot price as reference for strike
                snapshot = get_market_snapshot()
                if snapshot['spot_price']:
                    strike = snapshot['spot_price'] - 50  # Approximate strike
                else:
                    strike = 75000
                generate_report(market_data['slug'], strike)
                break
    else:
        print("No BTC markets found")
