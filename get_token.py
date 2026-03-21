import requests

# 1. Get a list of active markets (Gamma API is public)
markets = requests.get("https://gamma-api.polymarket.com/markets",
                       params={"active": "true", "limit": 1}).json()

# 2. Extract the first market's token IDs
market = markets[0]
token_ids = market.get("clobTokenIds")      # list of two tokens (YES/NO)
print(f"Market: {market['question']}")
print(f"YES token ID: {token_ids[0]}")
