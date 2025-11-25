import os
import json
from datetime import datetime
from fastapi import FastAPI, Request, Response
from telegram import Update, Bot, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters

app = FastAPI()

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
MINI_APP_URL = os.getenv("MINI_APP_URL")

ptb_app = Application.builder().token(TOKEN).updater(None).build()

USER_DATA_FILE = "users.json"

keyboard = [['Watch Ads', 'Balance'], ['Refer and Earn', 'Bonus', 'Extra']]
markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def load_json(filename):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)


def get_user_data(user_id):
    users = load_json(USER_DATA_FILE)
    if str(user_id) not in users:
        users[str(user_id)] = {
            "balance": 0.0,
            "ads_watched": 0,
            "last_ad_time": None,
            "referrals": [],
            "joined_date": datetime.now().isoformat()
        }
        save_json(USER_DATA_FILE, users)
    return users[str(user_id)]


def update_user_data(user_id, data):
    users = load_json(USER_DATA_FILE)
    users[str(user_id)] = data
    save_json(USER_DATA_FILE, users)


async def start_command(update: Update, context):
    user_id = update.effective_user.id
    get_user_data(user_id)

    await update.message.reply_text(
        f"💰 Welcome to Money Making Bot, {update.effective_user.first_name}!\n\n"
        "Earn money by watching ads, referring friends, and claiming bonuses!\n\n"
        "Choose an option below:",
        reply_markup=markup
    )


async def watch_ads_handler(update: Update, context):
    user_data = get_user_data(update.effective_user.id)
    keyboard = [[
        InlineKeyboardButton(
            "▶️ Click to Watch Ad",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📺 *Ready to Earn Money?*\n\n"
        "Watch a short video ad and earn ₹3!\n\n"
        "✅ Click the button below to start watching\n"
        "✅ Video will play in Mini App\n"
        "✅ App closes automatically after completion\n"
        "✅ You'll receive your reward instantly\n\n"
        f"💰 Current Balance: ₹{user_data['balance']:.2f}\n"
        f"📊 Ads Watched Today: {user_data['ads_watched']}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def balance_handler(update: Update, context):
    user_data = get_user_data(update.effective_user.id)
    await update.message.reply_text(
        f"💰 *Your Account Balance*\n\n"
        f"💵 Balance: ₹{user_data['balance']:.2f}\n"
        f"📺 Ads Watched: {user_data['ads_watched']}\n"
        f"👥 Referrals: {len(user_data['referrals'])}\n\n"
        f"Keep watching ads and referring friends to earn more!",
        parse_mode="Markdown"
    )


async def button_handler(update: Update, context):
    text = update.message.text
    if text == 'Watch Ads':
        await watch_ads_handler(update, context)
    elif text == 'Balance':
        await balance_handler(update, context)
    elif text == 'Refer and Earn':
        await update.message.reply_text("👥 Refer friends and earn rewards! (Coming soon)")
    elif text == 'Bonus':
        await update.message.reply_text("🎁 Daily bonus feature coming soon!")
    elif text == 'Extra':
        await update.message.reply_text("⚡ Extra features coming soon!")
    else:
        await update.message.reply_text("Please use the buttons below ⬇️")


ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))


@app.post("/webhook")
async def webhook_endpoint(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, ptb_app.bot)
        await ptb_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        print(f"Error processing update: {e}")
        return Response(status_code=200)


@app.post("/ad-completed")
async def ad_completed(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        ad_result = data.get("result")
        if not user_id:
            return {"status": "error", "message": "user_id required"}

        user_data = get_user_data(user_id)
        if ad_result == "success":
            reward = 3.0
            user_data['balance'] += reward
            user_data['ads_watched'] += 1
            user_data['last_ad_time'] = datetime.now().isoformat()
            update_user_data(user_id, user_data)

            keyboard = [[
                InlineKeyboardButton("▶️ Watch Another Ad", web_app=WebAppInfo(url=MINI_APP_URL))
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await ptb_app.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 *Congratulations!*\n\n"
                    f"✅ You've earned ₹{reward:.2f}!\n\n"
                    f"💰 New Balance: ₹{user_data['balance']:.2f}\n"
                    f"📊 Total Ads Watched: {user_data['ads_watched']}\n\n"
                    "Want to earn more? Watch another ad!"
                ),
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return {"status": "success", "reward": reward, "new_balance": user_data['balance']}
        else:
            return {"status": "error", "message": "Ad not completed"}
    except Exception as e:
        print(f"Error in ad-completed endpoint: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/")
async def root():
    return {"status": "Bot is running", "webhook": WEBHOOK_URL, "mini_app": MINI_APP_URL}


@app.on_event("startup")
async def on_startup():
    await ptb_app.initialize()
    await ptb_app.start()

    if WEBHOOK_URL:
        await ptb_app.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        print(f"✅ Webhook set to: {WEBHOOK_URL}")
    else:
        print("⚠️ WEBHOOK_URL not set!")

    if MINI_APP_URL:
        print(f"✅ Mini App URL: {MINI_APP_URL}")
    else:
        print("⚠️ MINI_APP_URL not set!")


@app.on_event("shutdown")
async def on_shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
