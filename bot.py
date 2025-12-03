import logging
import os
import asyncio
import random
import time
from datetime import datetime, date
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from supabase import create_client, Client
from asyncio_throttle import Throttle

load_dotenv()

# Config
BOT_TOKEN = os.getenv('BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
MINI_APP_URL = os.getenv('MINI_APP_URL', 'https://your-mini-app.pages.dev/')
VPS_IP = os.getenv('VPS_IP', 'localhost')

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY]):
    raise ValueError("❌ Missing .env variables")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FastAPI App
app_fastapi = FastAPI(title="CashyAds v9.3", version="9.3 - UNLIMITED ADS")
app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Rate limiter (commands only)
command_limiter = Throttle(5, 60)

# ✅ PENDING REWARDS QUEUE (for bot DM notifications)
pending_rewards = {}

# Keyboards
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

# Database Functions
async def get_user(user_id: int):
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"DB get_user {user_id}: {e}")
        return None

async def update_user_atomic(user_id: int, data: dict):
    try:
        supabase.table('users').upsert({**data, 'id': user_id}).execute()
        return True
    except Exception as e:
        logger.error(f"DB update {user_id}: {e}")
        return False

def create_user(user_id: int, first_name: str, username: str = None, referrer_id: int = None):
    if referrer_id == user_id:
        referrer_id = None
    user_data = {
        'id': user_id, 'telegram_username': username, 'first_name': first_name,
        'balance': 0.0, 'referrals': 0, 'ads_watched': 0, 'total_earnings': 0.0,
        'commission_earned': 0.0, 'bonus_claimed': False, 'last_bonus_date': None,
        'referrer_id': referrer_id, 'created_at': datetime.utcnow().isoformat()
    }
    try:
        supabase.table('users').insert(user_data).execute()
        if referrer_id:
            supabase.table('users').update({
                'referrals': supabase.raw('referrals + 1'),
                'balance': supabase.raw('balance + 50')
            }).eq('id', referrer_id).execute()
        return True
    except Exception as e:
        logger.error(f"Create user {user_id}: {e}")
        return False

async def get_user_stats(user_id: int):
    user = await get_user(user_id)
    if user:
        return {
            'balance': float(user.get('balance', 0)),
            'referrals': int(user.get('referrals', 0)),
            'ads_watched': int(user.get('ads_watched', 0)),
            'total_earnings': float(user.get('total_earnings', 0)),
            'commission_earned': float(user.get('commission_earned', 0)),
            'bonus_claimed': user.get('bonus_claimed', False),
            'last_bonus_date': user.get('last_bonus_date')
        }
    return {'balance': 0, 'referrals': 0, 'ads_watched': 0, 'total_earnings': 0, 'commission_earned': 0}

# ✅ CHECK PENDING REWARDS → SEND BOT DM SUCCESS MESSAGE
async def check_pending_rewards(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if user_id in pending_rewards:
        reward_data = pending_rewards.pop(user_id)
        if time.time() - reward_data['timestamp'] < 60:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 Watch More Ads", web_app=WebAppInfo(url=MINI_APP_URL))]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ **Ad Watched Successfully!**\n\n"
                     f"💰 **+₹{reward_data['reward']:.2f}** added\n"
                     f"💵 **New Balance: ₹{reward_data['balance']:.2f}**\n\n"
                     f"🔥 Watch **UNLIMITED** more ads!",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )

# ✅ MONETAG WEBHOOK - UNLIMITED ADS (queues bot notification)
@app_fastapi.post("/cashyads/ad-completed")
async def ad_completed(request: Request):
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        result = data.get('result', '').lower()
        
        logger.info(f"🎬 Ad webhook: user={user_id}, result={result}")
        
        if result not in {'completed', 'success', 'video_completed', 'full_video'}:
            return JSONResponse({"success": False, "message": "Invalid result"})
        
        user = await get_user(user_id)
        if not user:
            return JSONResponse({"success": False, "message": "User not found"}, status_code=404)
        
        # 🔥 UNLIMITED REWARDS - NO COOLDOWN!
        reward = round(random.uniform(3, 5), 2)
        current_balance = float(user.get('balance', 0))
        current_earnings = float(user.get('total_earnings', 0))
        current_ads = int(user.get('ads_watched', 0))
        
        # Atomic update
        success = await update_user_atomic(user_id, {
            'balance': current_balance + reward,
            'total_earnings': current_earnings + reward,
            'ads_watched': current_ads + 1
        })
        
        if not success:
            return JSONResponse({"success": False, "message": "Database error"}, status_code=500)
        
        # Queue reward notification for NEXT user interaction
        pending_rewards[user_id] = {
            'reward': reward,
            'balance': current_balance + reward,
            'timestamp': time.time()
        }
        
        # 5% referral commission
        if user.get('referrer_id'):
            commission = reward * 0.05
            referrer = await get_user(user['referrer_id'])
            if referrer:
                await update_user_atomic(user['referrer_id'], {
                    'balance': float(referrer.get('balance', 0)) + commission,
                    'commission_earned': float(referrer.get('commission_earned', 0)) + commission
                })
        
        logger.info(f"✅ REWARD QUEUED: user={user_id}, ₹{reward}, balance=₹{current_balance + reward:.2f}")
        
        return JSONResponse({"success": True, "reward": reward, "queued": True})
    except Exception as e:
        logger.error(f"❌ Ad webhook error: {e}")
        raise HTTPException(status_code=500)

@app_fastapi.get("/health")
async def health():
    return {"status": "ok", "version": "9.3", "unlimited_ads": True}

# Bot Handlers (ALL check pending rewards first)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await command_limiter.acquire(user_id):
        await update.message.reply_text("⏳ Too fast! Wait a moment.")
        return
    
    await check_pending_rewards(context, user_id)
    
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0][4:])
            if referrer_id == user_id:
                referrer_id = None
        except:
            pass
    
    if not await get_user(user_id):
        create_user(user_id, update.effective_user.first_name, update.effective_user.username, referrer_id)
    
    stats = await get_user_stats(user_id)
    await update.message.reply_text(
        f"👋 **Welcome to CashyAds v9.3!**\n\n"
        f"💰 **UNLIMITED Ads → NON-STOP Earnings**\n\n"
        f"💵 Balance: `₹{stats['balance']:.2f}`\n"
        f"📺 Ads: `{stats['ads_watched']}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n\n"
        f"🚀 Click **Watch Ads** to start EARNING!",
        reply_markup=create_main_keyboard(), parse_mode='Markdown'
    )

async def watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    await update.message.reply_text(
        "🎬 **UNLIMITED Premium Video Ads**\n\n"
        f"💎 Watch **FULL video** → **₹3-5 INSTANTLY**\n"
        f"🔥 **NO LIMIT** - Watch as many as you want!\n\n"
        f"👇 **OPEN ADS NOW** 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 WATCH UNLIMITED ADS", web_app=WebAppInfo(url=MINI_APP_URL))]
        ]),
        parse_mode='Markdown'
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]])
    await update.message.reply_text(
        f"💵 **Your Balance**\n\n"
        f"`₹{stats['balance']:.2f}`\n\n"
        f"📊 Ads: `{stats['ads_watched']}` | Total: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n\n"
        f"💰 Keep watching ads to earn more!",
        reply_markup=keyboard, parse_mode='Markdown'
    )

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    stats = await get_user_stats(user_id)
    
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    await update.message.reply_text(
        f"👥 **Refer & Earn**\n\n"
        f"🔗 **Your Link:**\n`{link}`\n\n"
        f"💰 **₹50 per signup**\n"
        f"📈 **5% commission** on ALL their ads\n\n"
        f"📊 **Your Stats:**\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        parse_mode='Markdown', reply_markup=create_main_keyboard()
    )

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    user_id = update.effective_user.id
    today = date.today().isoformat()
    
    user = await get_user(user_id)
    if user and not user.get('bonus_claimed', False) and user.get('last_bonus_date') != today:
        bonus = 5.0
        current_balance = float(user.get('balance', 0))
        await update_user_atomic(user_id, {
            'balance': current_balance + bonus,
            'bonus_claimed': True,
            'last_bonus_date': today
        })
        stats = await get_user_stats(user_id)
        await update.message.reply_text(
            f"🎉 **Daily Bonus Claimed!**\n\n"
            f"💰 **+₹5.00**\n"
            f"💵 **New Balance: ₹{stats['balance']:.2f}**\n\n"
            f"✅ Reset tomorrow!",
            reply_markup=create_main_keyboard(), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🎁 **Daily Bonus** (₹5)\n\n"
            "❌ Already claimed today!\n"
            "⏰ Resets at midnight\n\n"
            "💰 Watch ads for more earnings!",
            reply_markup=create_main_keyboard(), parse_mode='Markdown'
        )

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    try:
        response = supabase.table('users').select('first_name, balance').order('balance', desc=True).limit(10).execute()
        leaderboard = response.data
        
        msg = "🏆 **TOP 10 Richest Users**\n\n"
        for i, user in enumerate(leaderboard, 1):
            msg += f"{i}. {user['first_name']} - ₹{float(user['balance']):.2f}\n"
        
        await update.message.reply_text(msg + "\n🔥 Be #1! Watch more ads!", 
                                       parse_mode='Markdown', reply_markup=create_main_keyboard())
    except:
        await update.message.reply_text("Leaderboard unavailable!", reply_markup=create_main_keyboard())

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    stats = await get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"⭐ **Your Stats**\n\n"
        f"💵 Balance: `₹{stats['balance']:.2f}`\n"
        f"📺 Ads: `{stats['ads_watched']}`\n"
        f"💸 Total: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        reply_markup=create_main_keyboard(), parse_mode='Markdown'
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    query = update.callback_query
    await query.answer()
    
    if query.data == "withdraw":
        stats = await get_user_stats(query.from_user.id)
        if stats['balance'] >= 100:
            await query.edit_message_text("💸 **Withdrawal Options**\n\nMin ₹100", 
                                        reply_markup=create_withdraw_keyboard())
        else:
            await query.edit_message_text(f"💵 **Minimum ₹100 to withdraw**\nCurrent: ₹{stats['balance']:.2f}")
    elif query.data.startswith("withdraw_"):
        if query.data == "withdraw_cancel":
            await query.edit_message_text("❌ Cancelled", reply_markup=create_main_keyboard())
        else:
            await query.edit_message_text("💸 **Coming Soon!**\n\nWithdrawals via UPI/Paytm/Bank/USDT")
    await query.message.reply_text("👇 Use menu:", reply_markup=create_main_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_pending_rewards(context, update.effective_user.id)
    text = update.message.text
    user_id = update.effective_user.id
    
    if not await command_limiter.acquire(user_id):
        return
    
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
            reply_markup=create_main_keyboard(), parse_mode='Markdown'
        )

# Run FastAPI + Telegram Bot
async def run_api():
    config = uvicorn.Config(app_fastapi, host="0.0.0.0", port=8001, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    logger.info("🤖 CashyAds v9.3 - UNLIMITED ADS + BOT DM NOTIFICATIONS")
    logger.info(f"🌐 Webhook: http://{VPS_IP}:8001/cashyads/ad-completed")
    logger.info(f"🌐 Health: http://{VPS_IP}:8001/health")
    logger.info(f"🌐 Mini App: {MINI_APP_URL}")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Run API in background + Bot polling
    api_task = asyncio.create_task(run_api())
    
    logger.info("✅ Bot + API Running - UNLIMITED EARNINGS!")
    await app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
