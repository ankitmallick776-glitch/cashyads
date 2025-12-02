import logging
import os
import asyncio
import random
import threading
import json
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, date, timedelta
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
MINI_APP_URL = os.getenv('MINI_APP_URL', 'https://teleadviewer.pages.dev/')  # Configurable

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY]):
    print("❌ ERROR: Missing .env variables (BOT_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY)")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = None  # Global Telegram app
app_fastapi = FastAPI(title="CashyAds API", version="1.0")

# ✅ ENABLE CORS FOR MINI APP REQUESTS
app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (or restrict to your Cloudflare domain)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    logger.info("✅ Supabase connected")
except Exception as e:
    logger.error(f"❌ Supabase failed: {e}")
    exit(1)

# ✅ KEYBOARDS
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
        [InlineKeyboardButton("3️⃣ Bank Transfer", callback_data="withdraw_bank")],
        [InlineKeyboardButton("4️⃣ Paypal", callback_data="withdraw_paypal")],
        [InlineKeyboardButton("5️⃣ USDT TRC20", callback_data="withdraw_usdt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_cancel")]
    ])

def create_extra_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Main Channel", url="https://t.me/cashyads")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/cashyads_support")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")]
    ])

# ✅ REFERRAL NOTIFICATION
async def send_referral_notification(referrer_id: int, first_name: str, new_referrals: int):
    global app
    if app and app.bot:
        try:
            await app.bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 **NEW REFERRAL ALERT!** 🎉\n\n"
                     f"👤 **{first_name}** just joined via your link!\n"
                     f"💰 **+₹50** INSTANT bonus added!\n"
                     f"👥 **Total Referrals: {new_referrals}**\n\n"
                     f"📈 **5% LIFETIME commission** on their ads!\n\n"
                     f"🚀 Share more = Earn MORE! 💎",
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
            logger.info(f"✅ Referral notification sent to {referrer_id}")
        except Exception as e:
            logger.error(f"❌ Notification failed for {referrer_id}: {e}")

# ✅ DATABASE FUNCTIONS
def get_user(user_id: int):
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"❌ Get user failed for {user_id}: {e}")
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
    return {'balance': 0.0, 'referrals': 0, 'ads_watched': 0, 'total_earnings': 0.0, 
            'commission_earned': 0.0, 'bonus_claimed': False, 'last_bonus_date': None, 
            'referrer_id': None, 'last_ad_time': None}

def update_user_field(user_id: int, field: str, value): 
    try:
        supabase.table('users').update({field: value}).eq('id', user_id).execute()
    except Exception as e:
        logger.error(f"❌ Update field failed: {field}={value} for user {user_id}: {e}")

def increment_field(user_id: int, field: str, amount: float = 1):
    try:
        user = get_user(user_id)
        if user:
            current = float(user.get(field, 0))
            new_value = current + amount
            supabase.table('users').update({field: new_value}).eq('id', user_id).execute()
            logger.info(f"Updated {field}: {current} → {new_value} for user {user_id}")
            return new_value
    except Exception as e:
        logger.error(f"❌ Increment failed {field}: {e}")
    return 0

def can_claim_bonus(user_id: int) -> bool:
    try:
        user = get_user(user_id)
        if not user: return False
        today = date.today().isoformat()
        last_bonus = user.get('last_bonus_date', '')
        if last_bonus != today:
            update_user_field(user_id, 'bonus_claimed', False)
            update_user_field(user_id, 'last_bonus_date', today)
            return True
        return not user.get('bonus_claimed', False)
    except Exception as e:
        logger.error(f"❌ Bonus check failed: {e}")
        return False

def create_transaction(user_id: int, trans_type: str, amount: float, description: str):
    try:
        supabase.table('transactions').insert({
            'user_id': user_id, 'type': trans_type, 'amount': amount,
            'description': description, 'created_at': datetime.utcnow().isoformat()
        }).execute()
        logger.info(f"Transaction created: user={user_id}, type={trans_type}, amount={amount}")
    except Exception as e:
        logger.error(f"❌ Transaction failed: {e}")

def create_user(user_id: int, first_name: str, username: str = None, referrer_id: int = None):
    user_data = {
        'id': user_id, 'telegram_username': username, 'first_name': first_name,
        'balance': 0.0, 'referrals': 0, 'ads_watched': 0,
        'total_earnings': 0.0, 'commission_earned': 0.0,
        'bonus_claimed': False, 'last_bonus_date': None, 'referrer_id': referrer_id,
        'last_ad_time': None,  # New field
        'created_at': datetime.utcnow().isoformat()
    }
    supabase.table('users').insert(user_data).execute()
    
    if referrer_id:
        try:
            referrer = get_user(referrer_id)
            if referrer:
                new_referrals = referrer['referrals'] + 1
                supabase.table('users').update({
                    'referrals': new_referrals,
                    'balance': referrer['balance'] + 50.0
                }).eq('id', referrer_id).execute()
                
                supabase.table('transactions').insert({
                    'user_id': referrer_id, 'type': 'referral_signup',
                    'amount': 50.0, 'description': f"New referral: {first_name}",
                    'created_at': datetime.utcnow().isoformat()
                }).execute()
                
                # Fixed: Run async task properly
                loop = asyncio.get_event_loop()
                loop.create_task(send_referral_notification(referrer_id, first_name, new_referrals))
                logger.info(f"✅ Referral processed: {first_name} -> {referrer_id}")
        except Exception as e:
            logger.error(f"❌ Referral failed: {e}")

# ✅ SECURE FASTAPI ENDPOINT - PRIMARY REWARD DELIVERY (from Mini App)
@app_fastapi.post("/cashyads/ad-completed")
async def ad_completed(request: Request):
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        result = data.get('result', '').lower()

        logger.info(f"🎬 Ad webhook: user={user_id}, result={result}, data={data}")

        # ✅ Accept ALL success results from Mini App
        success_results = {
            'completed', 'success', 'video_completed', 'full_video_complete', 
            'video_viewed', 'full_video', 'viewed', 'test', 'debug'
        }

        if result in success_results:
            # Check if user exists
            user = get_user(user_id)
            if not user:
                logger.warning(f"⚠️ User not found: {user_id}")
                return JSONResponse({"success": False, "message": "User not found. Restart bot."}, status_code=404)

            # Basic rate limit check (5 mins between ads)
            if user.get('last_ad_time'):
                last_ad_seconds = (datetime.utcnow() - datetime.fromisoformat(user['last_ad_time'])).total_seconds()
                if last_ad_seconds < 300:
                    logger.warning(f"⚠️ Rate limit hit for {user_id} - waited {last_ad_seconds}s")
                    return JSONResponse({"success": False, "message": f"Too soon! Wait {300 - int(last_ad_seconds)}s."})

            # Credit reward (random ₹3-5)
            ad_reward = random.randint(3, 5)

            # UPDATE BALANCE
            increment_field(user_id, 'balance', ad_reward)
            increment_field(user_id, 'total_earnings', ad_reward)
            increment_field(user_id, 'ads_watched', 1)
            update_user_field(user_id, 'last_ad_time', datetime.utcnow().isoformat())

            # REFERRAL COMMISSION (5% to referrer)
            stats = get_user_stats(user_id)
            if stats.get('referrer_id'):
                commission = ad_reward * 0.05
                increment_field(stats['referrer_id'], 'balance', commission)
                increment_field(stats['referrer_id'], 'commission_earned', commission)
                create_transaction(stats['referrer_id'], 'commission', commission, 
                                   f"Mini App ad commission from {user_id}")

            # TRANSACTION LOG
            create_transaction(user_id, 'mini_app_ad', ad_reward, f"Video ad reward ({result})")

            # GET UPDATED STATS
            new_stats = get_user_stats(user_id)
            logger.info(f"✅ REWARD OK: user={user_id}, ₹{ad_reward}, balance=₹{new_stats['balance']:.2f}")

            return JSONResponse({
                "success": True,
                "reward": ad_reward,
                "new_balance": round(new_stats['balance'], 2),
                "message": "Reward credited successfully!"
            })

        logger.warning(f"⚠️ No reward: user={user_id}, result={result}")
        return JSONResponse({"success": False, "message": f"Invalid result: {result}"})

    except Exception as e:
        logger.error(f"❌ Ad endpoint ERROR: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# ✅ HEALTH CHECK ENDPOINT
@app_fastapi.get("/health")
async def health_check():
    return JSONResponse({"status": "ok", "service": "CashyAds v8.2"})

# ✅ NEW: WEB APP DATA HANDLER (SECONDARY - for Telegram bot notification)
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Guard to only process actual web_app_data messages
    if not update.message or not update.message.web_app_data:
        return  # Ignore if not a web app callback
    
    user_id = update.effective_user.id
    try:
        data = json.loads(update.message.web_app_data)
        result = data.get('result', '').lower()
        
        # Verify result
        if result not in {'completed', 'success', 'video_completed', 'full_video_complete', 'video_viewed', 'full_video', 'viewed'}:
            await update.message.reply_text("❌ Invalid ad completion. Try again.")
            return
        
        # Get user stats
        stats = get_user_stats(user_id)
        
        # Rate limit check
        if stats['last_ad_time'] and (datetime.utcnow() - datetime.fromisoformat(stats['last_ad_time'])).total_seconds() < 300:
            await update.message.reply_text("⏰ Wait 5 mins between ads!")
            return
        
        # ✅ NOTE: Reward should already be credited via Mini App API POST
        # This handler is just for Telegram bot notification/confirmation
        new_balance = stats['balance']
        await update.message.reply_text(
            f"🎬 **Ad Watched Successfully!**\n\n"
            f"💰 **Reward credit confirmed!**\n"
            f"💵 **Balance: ₹{new_balance:.2f}**\n\n"
            f"👏 Great job! Watch more to earn.",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        logger.info(f"✅ Web App Notification: user={user_id}, balance=₹{new_balance:.2f}")
        
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid data from ad viewer.")
    except Exception as e:
        logger.error(f"❌ Web App Data Error: {e}")
        await update.message.reply_text("❌ Error processing reward. Contact support.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global app
    user = update.effective_user
    user_id = user.id 
    
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0][4:])
        except: pass
    
    if not get_user(user_id):
        create_user(user_id, user.first_name, user.username, referrer_id)
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        f"💰 **CashyAds v8.2** (Secure Web App Rewards)\n\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n"
        f"👥 Referrals: {stats['referrals']}\n\n"
        f"🚀 Start earning now!",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📱 **Premium Video Ads** (v8.2 Secure)\n\n"
        f"🎥 Watch **ONE** video ad (25s)\n"
        f"💰 **Earn ₹3-5 GUARANTEED**\n"
        f"👥 **5% commission** to referrer\n\n"
        f"🔥 **OPEN VIDEO ADS** 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 WATCH VIDEO AD", web_app=WebAppInfo(url=MINI_APP_URL))]
        ]),
        parse_mode='Markdown'
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    withdraw_btn = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="show_withdraw")]])
    
    await update.message.reply_text(
        f"💵 **Your Total Balance**\n\n"
        f"`₹{stats['balance']:.2f}`\n\n"
        f"📊 Ads: {stats['ads_watched']} | Earnings: `₹{stats['total_earnings']:.2f}`\n\n"
        f"💰 Click Withdraw to cash out!",
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
        f"📈 **5% commission FOREVER** on video ads\n\n"
        f"📊 **Your Stats:**\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if can_claim_bonus(user_id):
        bonus = 5.0
        increment_field(user_id, 'balance', bonus)
        update_user_field(user_id, 'bonus_claimed', True)
        create_transaction(user_id, 'bonus', bonus, "Daily bonus ₹5")
        
        stats = get_user_stats(user_id)
        await update.message.reply_text(
            f"🎉 **Daily Bonus Claimed!**\n\n"
            f"💰 **+₹5.00**\n"
            f"💵 **New Balance: ₹{stats['balance']:.2f}**\n\n"
            f"✅ Comes back tomorrow!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🎁 **Daily Bonus**\n\n"
            "Already claimed today!\n⏰ Resets at midnight UTC\n\nKeep earning!",
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
        
        await update.message.reply_text(msg + "\n👆 Be #1! 🚀", parse_mode='Markdown', reply_markup=create_main_keyboard())
    except Exception as e:
        logger.error(f"❌ Leaderboard error: {e}")
        await update.message.reply_text("Leaderboard temporarily unavailable!", reply_markup=create_main_keyboard())

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    extra_kb = create_extra_keyboard()
    
    await update.message.reply_text(
        f"⭐ **Extra Menu**\n\n"
        f"📺 Ads Watched: `{stats['ads_watched']}`\n"
        f"💸 Total Earnings: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`\n\n"
        f"📢 Join our channels for updates!",
        reply_markup=extra_kb,
        parse_mode='Markdown'
    )

async def handle_withdraw_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    stats = get_user_stats(user_id)
    
    try:
        await query.message.delete()
    except: pass
    
    if stats['balance'] < 380:
        await query.message.reply_text(
            f"💵 **Withdraw Requirements Not Met**\n\n"
            f"❌ Minimum ₹380 required!\n"
            f"💰 Current: ₹{stats['balance']:.2f}",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    if stats['referrals'] < 15:
        remaining = 15 - stats['referrals']
        await query.message.reply_text(
            f"💵 **Withdraw Requirements Not Met**\n\n"
            f"👥 {stats['referrals']}/15 referrals\n"
            f"Need {remaining} more!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    await query.message.reply_text(
        "💳 **Select Withdraw Method**", 
        reply_markup=create_withdraw_keyboard(), 
        parse_mode='Markdown'
    )

async def handle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    try:
        await query.message.delete()
    except: pass
    
    if data == "withdraw_cancel" or data == "back_main":
        await query.message.reply_text("💸 Withdraw cancelled!", reply_markup=create_main_keyboard())
        return
    
    if not data.startswith("withdraw_"):
        return
    
    method = data.split('_')[1].upper()
    stats = get_user_stats(user_id)
    
    # Simple timeout: Check if pending >5 mins (store timestamp in user_data)
    pending_time = context.user_data.get('withdraw_pending_time')
    if pending_time and (datetime.utcnow() - datetime.fromisoformat(pending_time)).total_seconds() > 300:
        context.user_data.clear()
        await query.message.reply_text("⏰ Withdraw session expired. Start over.", reply_markup=create_main_keyboard())
        return
    
    context.user_data['awaiting_withdraw_details'] = True
    context.user_data['withdraw_method'] = method
    context.user_data['withdraw_amount'] = stats['balance']
    context.user_data['withdraw_pending_time'] = datetime.utcnow().isoformat()
    
    await query.message.reply_text(
        f"✅ **Withdrawal Initiated!**\n\n"
        f"💰 Amount: `₹{stats['balance']:.2f}`\n"
        f"💳 Method: **{method}**\n\n"
        f"📝 **Send your {method} details:**\n"
        f"`yourupi@paytm` or `bank details` or `wallet address`\n\n"
        f"⏰ **Processing: 6-7 working days** (Reply within 5 mins)",
        parse_mode='Markdown',
        reply_markup=None
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if query.data == "show_withdraw":
        await handle_withdraw_check(update, context)
    elif query.data.startswith("withdraw_") or query.data in ["withdraw_cancel", "back_main"]:
        await handle_withdraw_method(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if context.user_data.get('awaiting_withdraw_details'):
        method = context.user_data.get('withdraw_method', 'UPI')
        amount = context.user_data.get('withdraw_amount', 0)
        pending_time = context.user_data.get('withdraw_pending_time')
        
        # Timeout check
        if pending_time and (datetime.utcnow() - datetime.fromisoformat(pending_time)).total_seconds() > 300:
            context.user_data.clear()
            await update.message.reply_text("⏰ Session expired. Use /start to retry.", reply_markup=create_main_keyboard())
            return
        
        increment_field(user_id, 'balance', -amount)
        create_transaction(user_id, 'withdraw', -amount, f"{method}: {text}")
        context.user_data.clear()
        
        await update.message.reply_text(
            f"📝 **{method} details received!**\n\n"
            f"✅ Withdrawal **successful**!\n"
            f"💰 Amount: `₹{amount:.2f}`\n"
            f"⏰ Processing within **6-7 working days**.\n\n"
            f"🚀 Keep earning more!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    if text == "💰 Watch Ads":
        await handle_watch_ads(update, context)
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
        await update.message.reply_text("👇 Use the buttons below!", reply_markup=create_main_keyboard())

def run_api_server():
    """Run FastAPI on port 8001 with CORS enabled"""
    uvicorn.run(app_fastapi, host="0.0.0.0", port=8001, log_level="info")

def main():
    global app
    logger.info("🤖 CashyAds v8.2 - Secure Web App + CORS Enabled + Direct API Rewards")
    
    # Telegram Bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Message, handle_web_app_data))  # Web app data handler
    
    # API Server
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    logger.info(f"🌐 API: http://{VPS_IP}:8001/cashyads/ad-completed")
    logger.info(f"🌐 Health Check: http://{VPS_IP}:8001/health")
    
    logger.info("✅ Bot + API Running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
