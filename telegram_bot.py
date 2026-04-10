import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ORACLE_URL = os.getenv("PRICE_ORACLE_URL")

def get_oracle_data(asset='btc', interval='5m'):
    try:
        resp = requests.get(f"{ORACLE_URL}/api/price/{asset}/{interval}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

async def signal_btc5m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_oracle_data('btc', '5m')
    if not data:
        await update.message.reply_text("❌ Oracle not responding")
        return
    # Determine cheaper side
    if data['up'] < data['down']:
        rec = "BUY UP"
    else:
        rec = "BUY DOWN"
    msg = (f"📈 *{data['title']}*\n"
           f"Slug: `{data['slug']}`\n\n"
           f"UP: {data['upCents']}¢\n"
           f"DOWN: {data['downCents']}¢\n\n"
           f"🎯 *Recommendation*: {rec} (cheaper side)")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot ready. Use /signalbtc5m")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signalbtc5m", signal_btc5m))
    app.run_polling()

if __name__ == "__main__":
    main()
