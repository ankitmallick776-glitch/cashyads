import logging
import os
import asyncio
import random
import threading
import json
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, date
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from supabase import create_client, Client

BOT_TOKEN = os.getenv('BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
VPS_IP = os.getenv('VPS_IP', 'localhost')
MINI_APP_URL = os.getenv('MINI_APP_URL', 'https://your-mini-app.pages.dev/')  # UPDATE THIS

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY]):
    print("❌ ERROR: Missing .env variables")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = None
app_fastapi = FastAPI(title="CashyAds v9.1", version="9.1")

app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
logger.info("✅ Supabase connected")

# KEYBOARDS
def create_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💰 Watch Ads")],
        [KeyboardButton("💵 Balance"), KeyboardButton("👥 Refer & Earn")],
        [KeyboardButton("🎁 Bonus"), KeyboardButton("⭐ Leaderboard")],
        [KeyboardButton("⭐ Extra")]
    ], resize_keyboard=True)

def create_withdraw_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ UPI", callback_data="withdraw_upi")],
        [InlineKeyboardButton("2️⃣ Paytm", callback_data="withdraw_paytm")],
        [InlineKeyboardButton("3️⃣ Bank", callback_data="withdraw_bank")],
        [InlineKeyboardButton("4️⃣ Paypal", callback_data="withdraw_paypal")],
        [InlineKeyboardButton("5️⃣ USDT", callback_data="withdraw_usdt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_cancel")]
    ])

# DATABASE FUNCTIONS
def get_user(user_id: int):
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except:
        return None

def get_user_stats(user_id: int):
    user = get_user(user_id)
    if user:
        return {
            'balance': float(user.get('balance', 0)),
            'referrals': int(user.get('referrals', 0)),
            'ads_watched': int(user.get('ads_watched', 0)),
            'total_earnings': float(user.get('total_earnings', 0)),
            'commission_earned': float(user.get('commission_earned', 0)),
            'bonus_claimed': user.get('bonus_claimed', False),
            'last_bonus_date': user.get('last_bonus_date'),
            'referrer_id': user.get('referrer_id'),
            'last_ad_time': user.get('last_ad_time')
        }
    return {'balance': 0, 'referrals': 0, 'ads_watched': 0, 'total_earnings': 0, 
            'commission_earned': 0, 'bonus_claimed': False, 'last_bonus_date': None, 
            'referrer_id': None, 'last_ad_time': None}

def update_user(user_id: int, data: dict):
    try:
        supabase.table('users').update(data).eq('id', user_id).execute()
    except Exception as e:
        logger.error(f"Update failed: {e}")

def increment_field(user_id: int, field: str, amount: float = 1):
    try:
        user = get_user(user_id)
        if user:
            current = float(user.get(field, 0))
            new_value = current + amount
            update_user(user_id, {field: new_value})
            return new_value
    except:
        pass
    return 0

def create_user(user_id: int, first_name: str, username: str = None, referrer_id: int = None):
    user_data = {
        'id': user_id, 'telegram_username': username, 'first_name': first_name,
        'balance': 0.0, 'referrals': 0, 'ads_watched': 0, 'total_earnings': 0.0,
        'commission_earned': 0.0, 'bonus_claimed': False, 'last_bonus_date': None,
        'referrer_id': referrer_id, 'last_ad_time': None, 'created_at': datetime.utcnow().isoformat()
    }
    supabase.table('users').insert(user_data).execute()
    
    if referrer_id:
        increment_field(referrer_id, 'balance', 50)
        increment_field(referrer_id, 'referrals', 1)

# ✅ MONETAG AD COMPLETION WEBHOOK - NO COOLDOWN!
@app_fastapi.post("/cashyads/ad-completed")
async def ad_completed(request: Request):
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        result = data.get('result', '').lower()
        
        logger.info(f"🎬 Ad webhook: user={user_id}, result={result}")
        
        if result in {'completed', 'success', 'video_completed', 'full_video'}:
            user = get_user(user_id)
            if not user:
                return JSONResponse({"success": False, "message": "User not found"}, status_code=404)
            
            # ✅ NO RATE LIMIT - UNLIMITED ADS ALLOWED!
            
            # Reward: ₹3-5 random
            reward = random.uniform(3, 5)
            
            # Credit user
            increment_field(user_id, 'balance', reward)
            increment_field(user_id, 'total_earnings', reward)
            increment_field(user_id, 'ads_watched', 1)
            
            # Referral commission 5%
            stats = get_user_stats(user_id)
            if stats.get('referrer_id'):
                commission = reward * 0.05
                increment_field(stats['referrer_id'], 'balance', commission)
                increment_field(stats['referrer_id'], 'commission_earned', commission)
            
            stats = get_user_stats(user_id)
            logger.info(f"✅ REWARD: user={user_id}, ₹{reward:.2f}, balance=₹{stats['balance']:.2f}")
            
            return JSONResponse({
                "success": True, 
                "reward": round(reward, 2), 
                "new_balance": round(stats['balance'], 2)
            })
        
        return JSONResponse({"success": False, "message": "Invalid result"})
    except Exception as e:
        logger.error(f"❌ Ad endpoint error: {e}")
        raise HTTPException(status_code=500)

@app_fastapi.get("/health")
async def health():
    return {"status": "ok", "service": "CashyAds v9.1 - UNLIMITED ADS"}

# HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0][4:])
        except:
            pass
    
    if not get_user(user_id):
        create_user(user_id, user.first_name, user.username, referrer_id)
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"👋 **Welcome to CashyAds v9.1!**\n\n"
        f"💰 **Watch UNLIMITED Ads → Earn NON-STOP**\n\n"
        f"💵 Balance: `₹{stats['balance']:.2f}`\n"
        f"📺 Ads: `{stats['ads_watched']}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n\n"
        f"🚀 Click **Watch Ads** to start EARNING!",
        reply_markup=create_main_keyboard(), parse_mode='Markdown'
    )

async def watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 **UNLIMITED Premium Video Ads** (Monetag)\n\n"
        f"💎 Watch **FULL video** → **Earn ₹3-5 INSTANTLY**\n"
        f"🔥 **NO LIMIT** - Watch as many as you want!\n\n"
        f"👇 **OPEN ADS NOW** 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 WATCH UNLIMITED ADS", web_app=WebAppInfo(url=MINI_APP_URL))]
        ]),
        parse_mode='Markdown'
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    withdraw_btn = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]])
    
    await update.message.reply_text(
        f"💵 **Your Balance**\n\n"
        f"`₹{stats['balance']:.2f}`\n\n"
        f"📊 Ads: `{stats['ads_watched']}` | Total: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n\n"
        f"💰 Keep watching ads to earn more!",
        reply_markup=withdraw_btn,
        parse_mode='Markdown'
    )

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    await update.message.reply_text(
        f"👥 **Refer & Earn**\n\n"
        f"🔗 **Your Link:**\n`{link}`\n\n"
        f"💰 **₹50 per signup**\n"
        f"📈 **5% commission** on ALL their ads\n\n"
        f"📊 **Your Stats:**\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = date.today().isoformat()
    
    user = get_user(user_id)
    if user and not user.get('bonus_claimed', False) and user.get('last_bonus_date') != today:
        bonus = 5.0
        increment_field(user_id, 'balance', bonus)
        update_user(user_id, {'bonus_claimed': True, 'last_bonus_date': today})
        
        stats = get_user_stats(user_id)
        await update.message.reply_text(
            f"🎉 **Daily Bonus Claimed!**\n\n"
            f"💰 **+₹5.00**\n"
            f"💵 **New Balance: ₹{stats['balance']:.2f}**\n\n"
            f"✅ Reset tomorrow!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🎁 **Daily Bonus** (₹5)\n\n"
            "❌ Already claimed today!\n"
            "⏰ Resets at midnight\n\n"
            "💰 Watch ads for more earnings!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = supabase.table('users').select('first_name, balance').order('balance', desc=True).limit(10).execute()
        leaderboard = response.data
        
        msg = "🏆 **TOP 10 Richest Users**\n\n"
        for i, user in enumerate(leaderboard, 1):
            msg += f"{i}. {user['first_name']} - ₹{float(user['balance']):.2f}\n"
        
        await update.message.reply_text(msg + "\n🔥 Be #1! Watch more ads!", parse_mode='Markdown', reply_markup=create_main_keyboard())
    except:
        await update.message.reply_text("Leaderboard unavailable!", reply_markup=create_main_keyboard())

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"⭐ **Your Stats**\n\n"
        f"💵 Balance: `₹{stats['balance']:.2f}`\n"
        f"📺 Ads: `{stats['ads_watched']}`\n"
        f"💸 Total: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "💰 Watch Ads":
        await watch_ads(update, context)
    elif text == "💵 Balance":
        await handle_balance(update, context)
    elif text == "👥 Refer & Earn":
        await handle_refer(update, context)
    elif text == "🎁 Bonus":
        await handle_bonus(update, context)
    elif text == "⭐ Leaderboard":
        await handle_leaderboard(update, context)
    elif text == "⭐ Extra":
        await handle_extra(update, context)
    else:
        await update.message.reply_text(
            "👇 **Choose an option:**\n\n"
            "💰 Watch **UNLIMITED ads**\n"
            "💵 Check balance\n"
            "👥 Refer friends",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )

def run_api():
    uvicorn.run(app_fastapi, host="0.0.0.0", port=8001, log_level="info")

def main():
    global app
    logger.info("🤖 CashyAds v9.1 - UNLIMITED ADS (No Cooldown)")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    logger.info(f"🌐 API: http://{VPS_IP}:8001/cashyads/ad-completed")
    logger.info(f"🌐 Health: http://{VPS_IP}:8001/health")
    logger.info(f"🌐 Mini App: {MINI_APP_URL}")
    
    logger.info("✅ Bot + API Running - UNLIMITED EARNINGS!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
