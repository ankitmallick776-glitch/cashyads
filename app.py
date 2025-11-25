import os
import asyncio
from fastapi import FastAPI
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters

app = FastAPI()

TOKEN = os.getenv("TELEGRAM_TOKEN")
MINI_APP_URL = os.getenv("MINI_APP_URL")

if not TOKEN:
    raise ValueError("Please set TELEGRAM_TOKEN environment variable")

# Setup Telegram Application (Polling - no webhook)
application = Application.builder().token(TOKEN).build()

USER_DATA_FILE = "users.json"

import json
from datetime import datetime

def load_user_data():
    try:
        with open(USER_DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_user_data(data):
    with open(USER_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(user_id):
    users = load_user_data()
    if str(user_id) not in users:
        users[str(user_id)] = {
            "balance": 0.0,
            "ads_watched": 0,
            "last_ad_time": None
        }
        save_user_data(users)
    return users[str(user_id)]

def update_user(user_id, data):
    users = load_user_data()
    users[str(user_id)] = data
    save_user_data(users)

# Handlers

async def start(update: Update, context):
    user_data = get_user(update.effective_user.id)
    keyboard = [
        ["Watch Ads", "Balance"],
        ["Refer and Earn", "Bonus", "Extra"]
    ]
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(text=btn, callback_data=btn)] for row in keyboard for btn in row
    ])
    welcome_text = (
        f"Welcome {update.effective_user.first_name}!\n"
        "Choose an option:\n"
        "1. Watch Ads to earn money\n"
        "2. Check your Balance\n"
        "3. Refer and Earn\n"
        "4. Bonuses\n"
        "5. Extra features coming soon!"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)

    if query.data == "Watch Ads":
        keyboard = [[InlineKeyboardButton("▶️ Click to Watch Ad", web_app=WebAppInfo(url=f"{MINI_APP_URL}?user_id={user_id}"))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Watch a video ad and earn ₹3! Click below to start watching.", reply_markup=reply_markup)
    elif query.data == "Balance":
        await query.message.reply_text(f"Your current balance is ₹{user_data['balance']:.2f}.\nAds watched: {user_data['ads_watched']}")
    else:
        await query.message.reply_text(f"The {query.data} feature is coming soon!")

application.add_handler(CommandHandler("start", start))
application.add_handler(Handler=MessageHandler(filters.TEXT & ~filters.COMMAND, callback=button_handler))
application.add_handler(MessageHandler(filters.COMMAND, callback=start)) # fallback

@app.get("/")
async def root():
    return {"status": "Bot running with polling"}

async def run_polling():
    await application.initialize()
    await application.start()
    print("Bot started long poll.")
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_polling())
