"""
External signals for Polymarket advisory bot.
"""

import yfinance as yf
import requests

class ExternalSignals:
    def get_cme_futures_change(self):
        try:
            ticker = yf.Ticker("BTC1!")
            hist = ticker.history(period="2d")
            if len(hist) < 2:
                return None
            prev_close = hist['Close'].iloc[-2]
            current = hist['Close'].iloc[-1]
            return (current - prev_close) / prev_close
        except:
            return None

    def get_binance_btc_orderbook_imbalance(self):
        try:
            url = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=10"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            bids = sum(float(b[1]) for b in data['bids'])
            asks = sum(float(a[1]) for a in data['asks'])
            if bids + asks == 0:
                return 0
            return (bids - asks) / (bids + asks)
        except:
            return None

    def get_news_sentiment(self):
        # Placeholder – returns neutral 0
        return 0.0
