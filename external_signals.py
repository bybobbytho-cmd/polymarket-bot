"""
External signals for Polymarket advisory bot.
Fetches data from CME futures, Binance order book, and news sentiment.
"""

import yfinance as yf
import requests
import time
from textblob import TextBlob
from typing import Optional, Dict

class ExternalSignals:
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 60  # seconds

    def get_cme_futures_change(self) -> Optional[float]:
        """
        Get the percentage change of CME Bitcoin futures (BTC1!) from previous close.
        Returns change as a fraction (e.g., 0.01 for 1%).
        """
        try:
            ticker = yf.Ticker("BTC1!")
            hist = ticker.history(period="2d")
            if len(hist) < 2:
                return None
            prev_close = hist['Close'].iloc[-2]
            current_price = hist['Close'].iloc[-1]
            change = (current_price - prev_close) / prev_close
            return change
        except Exception as e:
            print(f"Error fetching futures: {e}")
            return None

    def get_binance_btc_orderbook_imbalance(self) -> Optional[float]:
        """
        Fetch BTC/USDT order book from Binance and compute bid/ask imbalance.
        Returns a value between -1 (strong sell pressure) and +1 (strong buy pressure).
        """
        try:
            url = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=10"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            bids = sum(float(b[1]) for b in data['bids'])  # total quantity at top 10 bids
            asks = sum(float(a[1]) for a in data['asks'])
            if bids + asks == 0:
                return 0
            imbalance = (bids - asks) / (bids + asks)
            return imbalance
        except Exception as e:
            print(f"Error fetching Binance order book: {e}")
            return None

    def get_news_sentiment(self, query="Bitcoin") -> Optional[float]:
        """
        Fetch recent news headlines (using NewsAPI – requires free API key) and compute sentiment.
        If no API key, returns a neutral 0.
        """
        # Placeholder – returns 0 to avoid API key requirement.
        # You can replace with a real news source later.
        return 0.0

    def get_fair_value_yes(self) -> float:
        """
        Combine external signals into a fair value estimate for YES (0 to 1).
        """
        futures_change = self.get_cme_futures_change()
        binance_imbalance = self.get_binance_btc_orderbook_imbalance()
        news_sentiment = self.get_news_sentiment()

        if futures_change is None:
            futures_change = 0.0
        if binance_imbalance is None:
            binance_imbalance = 0.0

        # Map futures change (e.g., +1% -> 0.01) to a 0-1 score
        futures_score = 0.5 + 10 * futures_change
        futures_score = max(0.0, min(1.0, futures_score))

        # Map imbalance (-1..1) to 0-1
        imbalance_score = (binance_imbalance + 1) / 2

        # News sentiment (-1..1) to 0-1
        sentiment_score = (news_sentiment + 1) / 2

        # Combine weights (you can adjust later)
        fair_value = 0.4 * futures_score + 0.4 * imbalance_score + 0.2 * sentiment_score
        return fair_value
