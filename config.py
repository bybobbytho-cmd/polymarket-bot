"""
Polymarket Bot Configuration - Updated with Minute Market Discovery
Loads environment variables and provides utility functions for trading 5m/15m markets.
"""

import os
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

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

        # RPC URL for Polygon (for signing transactions)
        self.polygon_rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

        # Bot settings
        self.max_stake_percent = float(os.getenv("MAX_STAKE_PERCENT", "0.05"))
        self.daily_loss_limit_percent = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.05"))
        # FIXED: Minimum stake set to $1.00 (Polymarket minimum)
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

        # Validate private key format (basic check)
        if not self.private_key.startswith("0x") or len(self.private_key) != 66:
            print("⚠️ Warning: Private key may be invalid format. Should start with 0x and be 66 characters.")

    @property
    def account(self):
        """Get Ethereum account from private key."""
        return Account.from_key(self.private_key)


# ============================================================
# MINUTE MARKET DISCOVERY (WORKING METHOD)
# ============================================================

class MinuteMarketFinder:
    """
    Discovers current 5m and 15m BTC/ETH markets using deterministic slug generation.
    This is the ONLY reliable way to find these markets.
    """

    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"

    def get_current_window_timestamp(self, minutes=5):
        """
        Calculate the current window start timestamp in UTC.
        For 5m markets: rounds down to nearest 5 minutes
        For 15m markets: rounds down to nearest 15 minutes
        """
        now = datetime.utcnow()

        if minutes == 5:
            window_start = now - timedelta(
                minutes=now.minute % 5,
                seconds=now.second,
                microseconds=now.microsecond
            )
        else:  # 15 minutes
            window_start = now - timedelta(
                minutes=now.minute % 15,
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

    def discover_all_minute_markets(self):
        """
        Find all currently active 5m and 15m BTC/ETH markets.
        Returns a dictionary with all found markets.
        """
        markets = {}

        # Try all combinations
        for asset in ['btc', 'eth']:
            for minutes in [5, 15]:
                timestamp = self.get_current_window_timestamp(minutes)
                slug = f"{asset}-updown-{minutes}m-{timestamp}"

                market_data = self.get_market_by_slug(slug)
                if market_data:
                    key = f"{asset.upper()}_{minutes}m"
                    markets[key] = market_data
                    print(f"✅ Found {key}: {market_data['prices']}")

        return markets

    def monitor_continuously(self, interval=10):
        """
        Continuously monitor for new minute markets.
        Runs every `interval` seconds.
        """
        print(f"🔄 Starting minute market monitor (checking every {interval}s)")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                markets = self.discover_all_minute_markets()

                if markets:
                    print(f"\n📊 ACTIVE MARKETS FOUND:")
                    for key, data in markets.items():
                        print(f"   {key}: {data['prices']}")
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
        self.market_finder = MinuteMarketFinder()

        if not self.web3.is_connected():
            print("⚠️ Warning: Could not connect to Polygon RPC")

    def get_current_minute_markets(self):
        """Get all currently active minute markets."""
        return self.market_finder.discover_all_minute_markets()

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

    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id, message):
        """Send a message to a specific chat."""
        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram message: {e}")
            return False


# ============================================================
# TEST FUNCTION
# ============================================================

def test_bot():
    """Test all bot components."""
    print("=" * 60)
    print("Polymarket Bot - Minute Market Test")
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

    # ===== TELEGRAM CONNECTION TEST =====
    print("\n📡 TESTING TELEGRAM CONNECTION FROM RAILWAY:")
    if config.telegram_token:
        print(f"   Token found: {config.telegram_token[:10]}...")

        try:
            url = f"https://api.telegram.org/bot{config.telegram_token}/getMe"
            r = requests.get(url, timeout=15)
            print(f"   STATUS: {r.status_code}")
            if r.status_code == 200:
                print(f"   ✅ Telegram API reachable!")
                print(f"   Bot info: {r.json().get('result', {}).get('username')}")
            else:
                print(f"   ❌ Telegram error: {r.text[:200]}")
        except Exception as e:
            print(f"   ❌ TELEGRAM ERROR: {repr(e)}")
    else:
        print("   ❌ No Telegram token found")
    # =====================================

    # Test minute market discovery
    print("\n🔍 Discovering minute markets...")
    finder = MinuteMarketFinder()
    markets = finder.discover_all_minute_markets()

    if markets:
        print(f"\n✅ Found {len(markets)} active minute markets:")
        for key, data in markets.items():
            print(f"\n   📊 {key}: {data['title']}")
            print(f"      Market ID: {data['market_id']}")
            print(f"      Prices: {data['prices']}")
            print(f"      Ends: {data['end_date']}")
    else:
        print("\n⚠️ No minute markets currently active")
        print("   This is normal - try again in a few minutes")

    print("\n" + "=" * 60)
    print("Bot is ready to trade!")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    test_bot()
