import requests
import time
from datetime import datetime, timedelta, timezone

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

def candidate_window_starts(minutes=5):
    sec = minutes * 60
    now = int(time.time())
    remainder = now % sec
    return [now - remainder - sec, now - remainder]

def get_event_by_slug(slug):
    url = f"{GAMMA_API}/events"
    try:
        resp = requests.get(url, params={"slug": slug}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"Error fetching {slug}: {e}")
        return None

def clob_midpoints(token_ids):
    ids = [str(x) for x in token_ids if x]
    if len(ids) < 2:
        return {}
    # 1) GET /midpoints
    try:
        resp = requests.get(f"{CLOB_API}/midpoints", params={"token_ids": ",".join(ids)}, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data
    except Exception as e:
        print(f"GET /midpoints failed: {e}")
    # 2) POST /midpoints
    try:
        resp = requests.post(f"{CLOB_API}/midpoints", json=[{"token_id": tid} for tid in ids],
                              headers={"Content-Type": "application/json"}, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data
    except Exception as e:
        print(f"POST /midpoints failed: {e}")
    # 3) Individual GET /midpoint
    out = {}
    for tid in ids:
        try:
            resp = requests.get(f"{CLOB_API}/midpoint", params={"token_id": tid}, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                mp = data.get("mid_price") or data.get("midPrice")
                if mp:
                    out[tid] = str(mp)
        except Exception as e:
            print(f"GET /midpoint failed for {tid}: {e}")
    if out:
        return out
    # 4) Fallback: order book → compute midpoint from best bid/ask
    print("  Trying order book fallback...")
    for tid in ids:
        try:
            resp = requests.get(f"{CLOB_API}/book", params={"token_id": tid}, timeout=8)
            if resp.status_code == 200:
                book = resp.json()
                bids = book.get('bids', [])
                asks = book.get('asks', [])
                if bids and asks:
                    best_bid = float(bids[0]['price'])
                    best_ask = float(asks[0]['price'])
                    midpoint = (best_bid + best_ask) / 2
                    out[tid] = str(midpoint)
                elif bids:
                    out[tid] = str(float(bids[0]['price']))
                elif asks:
                    out[tid] = str(float(asks[0]['price']))
        except Exception as e:
            print(f"Order book failed for {tid}: {e}")
    return out

def test_btc_5m():
    starts = candidate_window_starts(5)
    print(f"Trying windows: {starts}")
    for start in starts:
        slug = f"btc-updown-5m-{start}"
        print(f"Checking slug: {slug}")
        event = get_event_by_slug(slug)
        if not event:
            print("  No event found")
            continue
        markets = event.get("markets", [])
        if not markets:
            print("  No markets in event")
            continue
        token_ids = markets[0].get("clobTokenIds")
        if not token_ids or len(token_ids) < 2:
            print("  No token IDs")
            continue
        print(f"  Token IDs: {token_ids}")
        mids = clob_midpoints([token_ids[0], token_ids[1]])
        print(f"  CLOB response: {mids}")
        if mids:
            up = mids.get(str(token_ids[0]))
            down = mids.get(str(token_ids[1]))
            if up and down:
                print(f"✅ SUCCESS: UP={up}, DOWN={down}")
                return True
    print("❌ No price data found")
    return False

if __name__ == "__main__":
    test_btc_5m()
