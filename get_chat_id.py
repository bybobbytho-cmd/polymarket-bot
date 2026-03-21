import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('TELEGRAM_TOKEN')

# First, send a message to your bot (you need to do this manually)
print("1️⃣  First, send ANY message to @Vengance48bot on Telegram")
input("2️⃣  Press Enter after you've sent the message...")

# Now get updates
url = f"https://api.telegram.org/bot{token}/getUpdates"
response = requests.get(url)

if response.status_code == 200:
    data = response.json()
    print("\n✅ Response received!")
    print(data)
    
    # Try to extract chat ID
    if data['result']:
        chat_id = data['result'][0]['message']['chat']['id']
        print(f"\n🎯 Your Chat ID is: {chat_id}")
        print("\nAdd this to your .env file as:")
        print(f"TELEGRAM_CHAT_ID={chat_id}")
    else:
        print("\n❌ No messages found. Send a message and try again.")
else:
    print(f"Error: {response.status_code}")
