"""
Polymarket Bot Configuration - BTC Only (5m, 15m, 1h)
Loads environment variables and provides utility functions for trading BTC markets.
"""

import os
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from regime import detect_regime
from executor import should_execute

# Load environment variables
load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

class Config:
    """Configuration settings loaded from environment variables."""

    def __init__(self):
        # Polymarket credentials
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        self.proxy_address = os.getenv("PROXY_ADDRESS")

        # Telegram
        self.telegram_token = os.getenv("TELEGRAM_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # RPC URL for Polygon (for signing transactions)
        self.polygon_rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

        # Bot settings
        self.max_stake_percent = float(os.getenv("MAX_STAKE_PERCENT", "0.05"))
        self.daily_loss_limit_percent = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.05"))
        self.min_stake_usd = float(os.getenv("MIN_STAKE_USD", "1.00"))

        # Validate required credentials
        self._validate()

    def _validate(self):
        """Check that all required credentials are present."""
        missing = []
        if not self.private_key:
            missing.append("POLYMARKET_PRIVATE_KEY")
        if not self.proxy_address:
            missing.append("PROXY_ADDRESS")
        if not self.telegram_token:
            missing.append("TELEGRAM_TOKEN")

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        if not self.private_key.startswith("0x") or len(self.private_key) != 66:
            print("⚠️ Warning: Private key may be invalid format. Should start with 0x and be 66 characters.")

    @property
    def account(self):
        """Get Ethereum account from private key."""
        return Account.from_key(self.private_key)


# ============================================================
# LIVE PRICE FROM ORACLE (RAILWAY)
# ============================================================

def get_live_price_from_oracle(asset='btc', interval='5m'):
    """Get live prices from Polymarket Oracle on Railway"""
    try:
        url = f"https://polymarket-oracle-production.up.railway.app/api/price/{asset}/{interval}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('up'), data.get('down'), data.get('slug')
    except Exception as e:
        print(f"Oracle error: {e}")
    return None, None, None


# ============================================================
# BTC MARKET DISCOVERY (5m, 15m, 1h ONLY)
# ============================================================

class BTCMarketFinder:
    """
    Discovers current BTC 5m, 15m, and 1h markets using deterministic slug generation.
    """

    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"

    def get_current_window_timestamp(self, minutes):
        """
        Calculate the current window start timestamp in UTC.
        """
        now = datetime.utcnow()

        if minutes == 5:
            window_start = now - timedelta(
                minutes=now.minute % 5,
                seconds=now.second,
                microseconds=now.microsecond
            )
        elif minutes == 15:
            window_start = now - timedelta(
                minutes=now.minute % 15,
                seconds=now.second,
                microseconds=now.microsecond
            )
        else:  # 60 minutes (1 hour)
            window_start = now - timedelta(
                minutes=now.minute % 60,
                seconds=now.second,
                microseconds=now.microsecond
            )

        return int(window_start.timestamp())

    def get_market_by_slug(self, slug):
        """Fetch a market using its exact slug."""
        url = f"{self.base_url}/events?slug={slug}"

        try:
            response = requests.get(url)
            if response.status_code == 200 and response.json():
                event = response.json()[0]
                if event.get('markets') and len(event['markets']) > 0:
                    market = event['markets'][0]
                    return {
                        'slug': slug,
                        'title': event.get('title'),
                        'event_id': event.get('id'),
                        'market_id': market.get('id'),
                        'condition_id': market.get('conditionId'),
                        'prices': market.get('outcomePrices'),
                        'volume': market.get('volume'),
                        'end_date': event.get('endDate')
                    }
            return None
        except Exception as e:
            print(f"Error fetching {slug}: {e}")
            return None

    def discover_btc_markets(self):
        """
        Find all currently active BTC markets: 5m, 15m, and 1h.
        Returns a dictionary with all found markets.
        """
        markets = {}
        
        # ONLY BTC, ONLY 5m, 15m, 1h
        for minutes in [5, 15, 60]:
            timestamp = self.get_current_window_timestamp(minutes)
            slug = f"btc-updown-{minutes}m-{timestamp}"
            
            market_data = self.get_market_by_slug(slug)
            if market_data:
                key = f"BTC_{minutes}m"
                markets[key] = market_data
                print(f"✅ Found {key}: {market_data['prices']}")

        return markets

    def monitor_continuously(self, interval=10):
        """
        Continuously monitor for new BTC markets.
        Runs every `interval` seconds.
        """
        print(f"🔄 Starting BTC market monitor (5m, 15m, 1h) - checking every {interval}s")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                markets = self.discover_btc_markets()

                if markets:
                    print(f"\n📊 ACTIVE BTC MARKETS FOUND:")
                    for key, data in markets.items():
                        print(f"   {key}: {data['prices']} | Ends: {data['end_date']}")
                else:
                    print(".", end="", flush=True)

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n🛑 Monitoring stopped")


# ============================================================
# POLYMARKET API CONNECTION
# ============================================================

class PolymarketAPI:
    """Wrapper for Polymarket API operations."""

    def __init__(self, config):
        self.config = config
        self.web3 = Web3(Web3.HTTPProvider(config.polygon_rpc_url))
        self.market_finder = BTCMarketFinder()

        if not self.web3.is_connected():
            print("⚠️ Warning: Could not connect to Polygon RPC")

    def get_current_btc_markets(self):
        """Get all currently active BTC markets (5m, 15m, 1h)."""
        return self.market_finder.discover_btc_markets()

    def get_market_price(self, market_id):
        """Get current price for a market."""
        url = f"https://gamma-api.polymarket.com/markets/{market_id}"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                return data.get('outcomePrices')
            return None
        except Exception as e:
            print(f"Error fetching price: {e}")
            return None


# ============================================================
# TELEGRAM ALERTS
# ============================================================

class TelegramAlert:
    """Send alerts to Telegram."""

    def __init__(self, token, chat_id=None):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, message, chat_id=None):
        """Send a message to Telegram."""
        send_to = chat_id or self.chat_id
        if not send_to:
            print("⚠️ No chat_id provided for Telegram message")
            return False

        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": send_to,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message: {e}")
            return False


# ============================================================
# REGIME-BASED MARKET ANALYSIS
# ============================================================

def analyze_market_with_regime(market_data, binance_obi, binance_velocity, cme_delta, distance_to_strike, rsi_1h):
    """
    Analyze a single market using our regime detection.
    Returns: verdict (BUY_UP/BUY_DOWN/PASS), reason, regime, confidence
    """
    
    # Detect regime
    regime, trade_dir, confidence, regime_reason = detect_regime(
        obi=binance_obi,
        cme_delta=cme_delta,
        distance_to_strike=distance_to_strike,
        velocity=binance_velocity,
        rsi_1h=rsi_1h
    )
    
    # Get execution decision
    price_position = -distance_to_strike if distance_to_strike > 0 else distance_to_strike
    
    execute, direction, size_mult, exec_reason = should_execute(
        regime=regime,
        trade_direction=trade_dir,
        price_position=price_position,
        distance_to_strike=distance_to_strike,
        confidence=confidence
    )
    
    if execute and direction:
        verdict = f"EXECUTE_{direction}"
        full_reason = f"{regime_reason} | {exec_reason} | Size: {int(size_mult*100)}%"
    else:
        verdict = "PASS"
        full_reason = f"{regime_reason} | {exec_reason}"
    
    return verdict, full_reason, regime, confidence


# ============================================================
# TEST FUNCTION
# ============================================================

def test_bot():
    """Test all bot components."""
    print("=" * 60)
    print("Polymarket Bot - BTC ONLY (5m, 15m, 1h) with Regime Detection")
    print("=" * 60)

    # Test configuration
    try:
        config = Config()
        print(f"✅ Configuration loaded")
        print(f"   Proxy: {config.proxy_address[:10]}...{config.proxy_address[-8:]}")
        print(f"   Min stake: ${config.min_stake_usd}")
    except Exception as e:
        print(f"❌ Config error: {e}")
        return

    # Test oracle connection
    print("\n🔗 TESTING ORACLE CONNECTION:")
    up, down, slug = get_live_price_from_oracle('btc', '5m')
    if up:
        print(f"   ✅ Oracle working!")
        print(f"   UP: {up}, DOWN: {down}")
        print(f"   Slug: {slug}")
    else:
        print(f"   ❌ Oracle not responding")

    # Test BTC market discovery
    print("\n🔍 Discovering BTC markets (5m, 15m, 1h)...")
    finder = BTCMarketFinder()
    markets = finder.discover_btc_markets()

    if markets:
        print(f"\n✅ Found {len(markets)} active BTC markets:")
        for key, data in markets.items():
            print(f"\n   📊 {key}: {data['title']}")
            print(f"      Market ID: {data['market_id']}")
            print(f"      Prices: {data['prices']}")
            print(f"      Ends: {data['end_date']}")
    else:
        print("\n⚠️ No BTC minute markets currently active")

    print("\n" + "=" * 60)
    print("BTC Bot is ready with REGIME DETECTION!")
    print("Markets tracked: BTC 5m, BTC 15m, BTC 1h")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    test_bot()
