import os
import requests
import time

def test_telegram():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    print("🔍 Testing Telegram from Railway...")
    print(f"Token starts with: {token[:10] if token else 'Not found'}")
    print(f"Chat ID: {chat_id if chat_id else 'Not found'}")
    
    # Test 1: Check bot info
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        r = requests.get(url, timeout=10)
        print(f"\n✅ Bot info: {r.json()}")
    except Exception as e:
        print(f"\n❌ Bot info failed: {e}")
    
    # Test 2: Send a message if we have chat_id
    if chat_id and chat_id != "123456789":
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": "🚀 Railway bot is alive and testing Telegram!"
        }
        try:
            r = requests.post(url, data=data, timeout=10)
            print(f"\n✅ Message sent: {r.json()}")
        except Exception as e:
            print(f"\n❌ Message failed: {e}")
    else:
        print("\n⚠️ No valid chat_id yet. Add TELEGRAM_CHAT_ID to Railway variables.")

if __name__ == "__main__":
    test_telegram()
