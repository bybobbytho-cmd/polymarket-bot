import os
import http.client
import json
from dotenv import load_dotenv
import time

load_dotenv()
token = os.getenv('TELEGRAM_TOKEN')

print("1️⃣  First, send ANY message to @Vengance48bot on Telegram")
input("2️⃣  Press Enter after you've sent the message...")

# Use HTTP instead of HTTPS
conn = http.client.HTTPConnection("api.telegram.org", 80)
conn.request("GET", f"/bot{token}/getUpdates")
response = conn.getresponse()
data = response.read()
conn.close()

print(f"\n✅ Status: {response.status}")
if response.status == 200:
    result = json.loads(data)
    print("Response received!")
    
    if result['result']:
        chat_id = result['result'][0]['message']['chat']['id']
        print(f"\n🎯 Your Chat ID is: {chat_id}")
        print("\nAdd this to your .env file as:")
        print(f"TELEGRAM_CHAT_ID={chat_id}")
    else:
        print("\n❌ No messages found. Make sure you sent a message to your bot.")
else:
    print(f"Error response: {data.decode()}")
