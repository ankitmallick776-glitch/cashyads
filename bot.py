import logging
import os
import random
import threading
import json
from datetime import datetime, date

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from supabase import create_client, Client

# ENV
BOT_TOKEN = os.getenv('BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
VPS_IP = os.getenv('VPS_IP', 'localhost')
MINI_APP_URL = os.getenv('MINI_APP_URL', 'https://teleadviewer.pages.dev/')

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY]):
    print("❌ ERROR: Missing .env variables (BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY)")
    raise SystemExit(1)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CashyAds")

# Globals
app = None
app_fastapi = FastAPI(title="CashyAds API", version="9.3")
user_chats: dict[int, int] = {}

# CORS
app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
logger.info("✅ Supabase connected")

# Keyboards
def create_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💰 Watch Ads")],
            [KeyboardButton("💵 Balance"), KeyboardButton("👥 Refer & Earn")],
            [KeyboardButton("🎁 Bonus"), KeyboardButton("⭐ Leaderboard")],
            [KeyboardButton("⭐ Extra")]
        ],
        resize_keyboard=True
    )

def watch_more_inline():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("▶️ WATCH MORE ADS", web_app=WebAppInfo(url=MINI_APP_URL))]]
    )

# DB helpers
def get_user(user_id: int):
    try:
        r = supabase.table('users').select('*').eq('id', user_id).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return None

def update_user(user_id: int, data: dict):
    try:
        supabase.table('users').update(data).eq('id', user_id).execute()
    except Exception as e:
        logger.error(f"update_user error: {e}")

def increment_field(user_id: int, field: str, amt: float = 1.0):
    try:
        u = get_user(user_id)
        if not u:
            return 0
        cur = float(u.get(field, 0) or 0)
        newv = cur + amt
        supabase.table('users').update({field: newv}).eq('id', user_id).execute()
        return newv
    except Exception as e:
        logger.error(f"increment_field error: {e}")
        return 0

def get_user_stats(user_id: int):
    u = get_user(user_id)
    if u:
        return {
            "balance": float(u.get("balance", 0) or 0),
            "referrals": int(u.get("referrals", 0) or 0),
            "ads_watched": int(u.get("ads_watched", 0) or 0),
            "total_earnings": float(u.get("total_earnings", 0) or 0),
            "commission_earned": float(u.get("commission_earned", 0) or 0),
            "bonus_claimed": bool(u.get("bonus_claimed", False)),
            "last_bonus_date": u.get("last_bonus_date"),
            "referrer_id": u.get("referrer_id"),
        }
    return {
        "balance": 0.0, "referrals": 0, "ads_watched": 0,
        "total_earnings": 0.0, "commission_earned": 0.0,
        "bonus_claimed": False, "last_bonus_date": None, "referrer_id": None
    }

def create_user(user_id: int, first_name: str, username: str | None = None, referrer_id: int | None = None):
    now = datetime.utcnow().isoformat()
    data = {
        "id": user_id,
        "telegram_username": username,
        "first_name": first_name,
        "balance": 0.0,
        "referrals": 0,
        "ads_watched": 0,
        "total_earnings": 0.0,
        "commission_earned": 0.0,
        "bonus_claimed": False,
        "last_bonus_date": None,
        "referrer_id": referrer_id,
        "created_at": now
    }
    supabase.table('users').insert(data).execute()
    if referrer_id:
        increment_field(referrer_id, "balance", 50.0)
        increment_field(referrer_id, "referrals", 1)

# FastAPI endpoints
@app_fastapi.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "CashyAds v9.3"})

@app_fastapi.post("/cashyads/ad-completed")
async def ad_completed(request: Request):
    """
    Mini App calls this after auto-closing (2s). Credits reward, updates DB,
    and sends a 'Watch more' message with updated balance.
    """
    try:
        body = await request.json()
        user_id = int(body.get("user_id"))
        result = str(body.get("result", "")).lower()
        reward = float(body.get("reward", random.uniform(3, 5)))

        if result != "completed":
            return JSONResponse({"success": False, "message": "Invalid result"})

        # Ensure user exists
        if not get_user(user_id):
            return JSONResponse({"success": False, "message": "User not found"}, status_code=404)

        # Credit user
        increment_field(user_id, "balance", reward)
        increment_field(user_id, "total_earnings", reward)
        increment_field(user_id, "ads_watched", 1)

        # Referral 5%
        st = get_user_stats(user_id)
        if st.get("referrer_id"):
            com = reward * 0.05
            increment_field(st["referrer_id"], "balance", com)
            increment_field(st["referrer_id"], "commission_earned", com)

        new_stats = get_user_stats(user_id)

        # Push message to chat (if known)
        chat_id = user_chats.get(user_id)
        if chat_id and app and app.bot:
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🎉 AD REWARD ADDED!\n\n"
                    f"💰 +₹{reward:.2f}\n"
                    f"💵 New Balance: ₹{new_stats['balance']:.2f}\n"
                    f"📺 Ads Watched: {new_stats['ads_watched']}"
                ),
                reply_markup=watch_more_inline()
            )

        return JSONResponse({
            "success": True,
            "reward": round(reward, 2),
            "new_balance": round(new_stats["balance"], 2)
        })
    except Exception as e:
        logger.error(f"/ad-completed error: {e}")
        raise HTTPException(status_code=500, detail="Server error")

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    # Remember chat for push notifications after Mini App closes
    user_chats[uid] = update.effective_chat.id

    # Referral param
    ref_id = None
    if context.args and len(context.args) > 0 and str(context.args[0]).startswith("ref_"):
        try:
            ref_id = int(str(context.args[0])[4:])
        except:
            ref_id = None

    if not get_user(uid):
        create_user(uid, user.first_name or "", user.username, ref_id)

    s = get_user_stats(uid)
    await update.message.reply_text(
        "👋 Welcome to CashyAds v9.3\n\n"
        "💰 Watch ads → Auto reward\n"
        f"💵 Balance: ₹{s['balance']:.2f}\n"
        f"📺 Ads: {s['ads_watched']}\n\n"
        "Tap Watch Ads to start.",
        reply_markup=create_main_keyboard()
    )

async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_chats[uid] = update.effective_chat.id
    await update.message.reply_text(
        "🎬 Ad will play instantly and the app will auto-close in 2 seconds.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("▶️ WATCH AD NOW", web_app=WebAppInfo(url=MINI_APP_URL))]]
        )
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"💵 Balance: ₹{s['balance']:.2f}\n"
        f"📺 Ads Watched: {s['ads_watched']}\n"
        f"💸 Total Earnings: ₹{s['total_earnings']:.2f}",
        reply_markup=watch_more_inline()
    )

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    uid = update.effective_user.id
    s = get_user_stats(uid)
    link = f"https://t.me/{bot_username}?start=ref_{uid}"
    await update.message.reply_text(
        "👥 Refer & Earn\n\n"
        f"🔗 Your Link:\n{link}\n\n"
        "₹50 per signup + 5% lifetime commission.",
        reply_markup=watch_more_inline()
    )

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = get_user_stats(uid)
    today = date.today().isoformat()
    if not s["bonus_claimed"] or s["last_bonus_date"] != today:
        increment_field(uid, "balance", 5.0)
        update_user(uid, {"bonus_claimed": True, "last_bonus_date": today})
        ns = get_user_stats(uid)
        await update.message.reply_text(
            f"🎉 Daily Bonus +₹5.00\nNew Balance: ₹{ns['balance']:.2f}",
            reply_markup=watch_more_inline()
        )
    else:
        await update.message.reply_text("🎁 Bonus already claimed today.", reply_markup=watch_more_inline())

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = supabase.table('users').select('first_name,balance').order('balance', desc=True).limit(10).execute()
        lb = res.data or []
        txt = "🏆 Top 10 Balances\n\n"
        for i, u in enumerate(lb, start=1):
            txt += f"{i}. {u.get('first_name','User')} - ₹{float(u.get('balance',0) or 0):.2f}\n"
        await update.message.reply_text(txt, reply_markup=watch_more_inline())
    except Exception as e:
        logger.error(f"leaderboard error: {e}")
        await update.message.reply_text("Leaderboard unavailable.", reply_markup=create_main_keyboard())

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        "⭐ Extra\n\n"
        f"📺 Ads: {s['ads_watched']} | 💸 Total: ₹{s['total_earnings']:.2f}\n"
        f"👥 Referrals: {s['referrals']} | 💎 Commission: ₹{s['commission_earned']:.2f}",
        reply_markup=watch_more_inline()
    )

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_chats[uid] = update.effective_chat.id
    txt = update.message.text

    if txt == "💰 Watch Ads":
        return await handle_watch_ads(update, context)
    if txt == "💵 Balance":
        return await handle_balance(update, context)
    if txt == "👥 Refer & Earn":
        return await handle_refer(update, context)
    if txt == "🎁 Bonus":
        return await handle_bonus(update, context)
    if txt == "⭐ Leaderboard":
        return await handle_leaderboard(update, context)
    if txt == "⭐ Extra":
        return await handle_extra(update, context)

    await update.message.reply_text("👇 Use the menu below.", reply_markup=create_main_keyboard())

def run_api():
    uvicorn.run(app_fastapi, host="0.0.0.0", port=8001, log_level="info")

def main():
    global app
    logger.info("🤖 CashyAds v9.3 starting...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lambda u, c: None))  # placeholder
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # API thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    logger.info(f"🌐 API: http://{VPS_IP}:8001/cashyads/ad-completed")
    logger.info(f"🌐 Mini App: {MINI_APP_URL}")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
