import os
import http.client
import ssl
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('TELEGRAM_TOKEN')

# Use HTTP (not HTTPS) to bypass SSL issues
conn = http.client.HTTPConnection("api.telegram.org", 80)
conn.request("GET", f"/bot{token}/getMe")
response = conn.getresponse()
data = response.read()

print(f"Status: {response.status}")
print(f"Response: {data.decode()}")
conn.close()
