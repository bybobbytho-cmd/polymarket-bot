#!/usr/bin/env python3
"""
Live simulation of maker strategy on Polymarket BTC 5m market.
Runs for 5 minutes, polls order book every 5 seconds.
"""

import time
import requests
import json
import sys
from datetime import datetime

# ---------- Configuration ----------
SIMULATION_DURATION = 300  # 5 minutes in seconds
POLL_INTERVAL = 5          # seconds between polls
REBATE_PCT = 0.002         # 0.2% maker rebate (adjustable)

# Global state
capital = 10.0             # starting paper capital
open_orders = []           # list of dicts: {'side', 'price', 'size', 'filled'}
fills = []                 # list of filled trades
pnl = 0.0
rebates = 0.0

def get_market_data(interval='5m'):
    """Fetch current market slug, best bid, best ask."""
    period = 300 if interval == '5m' else 900
    now = int(time.time())
    window_start = now - (now % period)
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                market = data[0]
                best_bid = market.get('bestBid')
                best_ask = market.get('bestAsk')
                if best_bid is not None and best_ask is not None:
                    return slug, float(best_bid), float(best_ask)
    except:
        pass
    # fallback to previous window
    window_start -= period
    slug = f"btc-updown-{interval}-{window_start}"
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                market = data[0]
                best_bid = market.get('bestBid')
                best_ask = market.get('bestAsk')
                if best_bid is not None and best_ask is not None:
                    return slug, float(best_bid), float(best_ask)
    except:
        pass
    return None, None, None

def place_limit_order(side, price, size):
    """Add a limit order to the open orders list."""
    global capital
    if side == 'BUY':
        # Reserve capital
        if capital < size * price:
            print(f"❌ Insufficient capital (need ${size*price:.2f}, have ${capital:.2f})")
            return False
        capital -= size * price
    open_orders.append({
        'side': side,
        'price': price,
        'size': size,
        'filled': False,
        'timestamp': time.time()
    })
    print(f"📝 Placed {side} limit order at ${price:.3f} for {size} shares (${size*price:.2f})")
    return True

def check_fills(bid, ask):
    """Check if any open orders are filled based on current bid/ask."""
    global capital, pnl, rebates
    for order in open_orders:
        if order['filled']:
            continue
        filled = False
        if order['side'] == 'BUY' and ask <= order['price']:
            filled = True
            # When our buy limit order at price is taken, we pay that price.
            # Later we will sell to close. For now, we just mark it filled.
            # We'll record the fill and add rebate.
            rebates += order['size'] * REBATE_PCT
            order['filled'] = True
            fills.append(order)
            print(f"✅ FILLED: {order['side']} {order['size']} shares at ${order['price']:.3f} (rebate +${order['size']*REBATE_PCT:.4f})")
        elif order['side'] == 'SELL' and bid >= order['price']:
            filled = True
            # When we sell, we receive the sale proceeds and also earn rebate.
            sale_proceeds = order['size'] * order['price']
            capital += sale_proceeds
            # Calculate profit: sale proceeds - cost (if we had bought earlier)
            # For simplicity, we'll assume this is a standalone sell order (short). But for maker, we usually have a paired buy.
            # We'll just track profit as sale proceeds minus initial cost (0 if no cost recorded). This is simplistic.
            # Better to track by matching with a previous buy order.
            # For this simulation, we'll treat each order independently and assume we already had the shares.
            # To keep it simple, we'll assume this is a closing order and we will later compute profit by pairing.
            # Let's just record fill and add rebate.
            rebates += order['size'] * REBATE_PCT
            order['filled'] = True
            fills.append(order)
            print(f"✅ FILLED: {order['side']} {order['size']} shares at ${order['price']:.3f} (rebate +${order['size']*REBATE_PCT:.4f})")

def print_status(bid, ask, elapsed):
    print(f"\n--- {datetime.now().strftime('%H:%M:%S')} | Elapsed: {elapsed:.0f}s ---")
    print(f"Market: Bid ${bid:.3f} | Ask ${ask:.3f} | Spread: {(ask-bid)/bid*100:.2f}%")
    print(f"Capital: ${capital:.2f} | Open orders: {len([o for o in open_orders if not o['filled']])} | Fills: {len(fills)}")
    print(f"Rebates earned: ${rebates:.4f}")

def main():
    print("🔍 Fetching current BTC 5m market...")
    slug, bid, ask = get_market_data('5m')
    if not slug:
        print("❌ Could not fetch market data. Exiting.")
        return
    print(f"✅ Market: {slug}")
    print(f"Initial bid: ${bid:.3f}, ask: ${ask:.3f}")
    
    # Ask user for limit order
    print("\n📊 Options:")
    print("1) Place a BUY limit order at the current best bid")
    print("2) Place a SELL limit order at the current best ask")
    print("3) Custom limit order (enter price)")
    choice = input("Enter choice (1/2/3): ").strip()
    side = None
    price = None
    size = 0.5  # default $0.50 stake
    if choice == '1':
        side = 'BUY'
        price = bid
    elif choice == '2':
        side = 'SELL'
        price = ask
    elif choice == '3':
        side = input("Side (BUY/SELL): ").strip().upper()
        price = float(input("Limit price: ").strip())
    else:
        print("Invalid choice, exiting.")
        return
    
    if not place_limit_order(side, price, size):
        return
    
    print(f"\n🔄 Starting simulation for {SIMULATION_DURATION} seconds (polling every {POLL_INTERVAL}s)...")
    start_time = time.time()
    last_print = 0
    try:
        while time.time() - start_time < SIMULATION_DURATION:
            elapsed = time.time() - start_time
            # Fetch current bid/ask
            _, new_bid, new_ask = get_market_data('5m')
            if new_bid is not None and new_ask is not None:
                bid, ask = new_bid, new_ask
                # Check fills
                check_fills(bid, ask)
                # Print status every 30 seconds
                if int(elapsed) % 30 < POLL_INTERVAL and elapsed - last_print > 25:
                    print_status(bid, ask, elapsed)
                    last_print = elapsed
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n⏹️ Simulation interrupted.")
    
    # Final report
    print("\n" + "="*50)
    print("📊 SIMULATION SUMMARY")
    print(f"Duration: {time.time() - start_time:.0f} seconds")
    print(f"Final capital: ${capital:.2f}")
    print(f"Open orders: {len([o for o in open_orders if not o['filled']])}")
    print(f"Filled orders: {len(fills)}")
    print(f"Rebates earned: ${rebates:.4f}")
    # Calculate total PnL (change in capital + rebates - initial capital)
    total_pnl = (capital - 10.0) + rebates
    print(f"Total PnL (incl. rebates): ${total_pnl:.4f}")
    print("="*50)

if __name__ == "__main__":
    main()
