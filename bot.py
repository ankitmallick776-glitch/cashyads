import logging
import os
import random
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()  # Load .env file automatically

# Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def get_user(user_id: int):
    response = supabase.table('users').select('*').eq('id', user_id).execute()
    return response.data[0] if response.data else None

def create_user(user_id: int, first_name: str, username: str = None, referrer_id: int = None):
    user_data = {
        'id': user_id,
        'telegram_username': username,
        'first_name': first_name,
        'balance': 0,
        'referrals': 0,
        'ads_watched': 0,
        'total_earnings': 0,
        'commission_earned': 0,
        'bonus_claimed': False,
        'last_bonus_date': None,
        'referrer_id': referrer_id,
        'created_at': datetime.utcnow().isoformat()
    }
    supabase.table('users').insert(user_data).execute()
    
    if referrer_id:
        referrer_stats = get_user_stats(referrer_id)
        supabase.table('users').update({
            'referrals': referrer_stats['referrals'] + 1,
            'balance': referrer_stats['balance'] + 50.0
        }).eq('id', referrer_id).execute()
        
        supabase.table('transactions').insert({
            'user_id': referrer_id,
            'type': 'referral_signup',
            'amount': 50.0,
            'description': f"New referral: {first_name}"
        }).execute()

def get_user_stats(user_id: int):
    user = get_user(user_id)
    if user:
        return {
            'balance': user.get('balance', 0),
            'referrals': user.get('referrals', 0),
            'ads_watched': user.get('ads_watched', 0),
            'total_earnings': user.get('total_earnings', 0),
            'commission_earned': user.get('commission_earned', 0),
            'bonus_claimed': user.get('bonus_claimed', False),
            'last_bonus_date': user.get('last_bonus_date'),
            'referrer_id': user.get('referrer_id')
        }
    return {}

def update_user_field(user_id: int, field: str, value):
    supabase.table('users').update({field: value}).eq('id', user_id).execute()

def increment_field(user_id: int, field: str, amount: float = 1):
    user = get_user(user_id)
    if user:
        current = user.get(field, 0)
        new_value = current + amount
        supabase.table('users').update({field: new_value}).eq('id', user_id).execute()
        return new_value
    return 0

def can_claim_bonus(user_id: int) -> bool:
    """v6 Fixed: Proper daily reset at midnight UTC"""
    user = get_user(user_id)
    if not user:
        return False
    
    last_bonus_date = user.get('last_bonus_date')
    today = date.today().isoformat()
    
    # Reset bonus if new day or never claimed
    if not last_bonus_date or last_bonus_date != today:
        update_user_field(user_id, 'bonus_claimed', False)
        update_user_field(user_id, 'last_bonus_date', today)
        return True
    
    return not user.get('bonus_claimed', False)

def create_transaction(user_id: int, trans_type: str, amount: float, description: str):
    supabase.table('transactions').insert({
        'user_id': user_id,
        'type': trans_type,
        'amount': amount,
        'description': description,
        'created_at': datetime.utcnow().isoformat()
    }).execute()

def create_main_keyboard():
    keyboard = [
        [KeyboardButton("💰 Watch Ads"), KeyboardButton("💵 Balance")],
        [KeyboardButton("👥 Refer and Earn"), KeyboardButton("🎁 Bonus")],
        [KeyboardButton("⭐ Leaderboard"), KeyboardButton("📊 Stats")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    referrer_id = None
    if context.args:
        if context.args[0].startswith('ref_'):
            try:
                referrer_id = int(context.args[0][4:])
            except:
                pass
    
    existing = get_user(user_id)
    if not existing:
        create_user(user_id, user.first_name, user.username, referrer_id)
        if referrer_id:
            try:
                await context.bot.send_message(
                    referrer_id, 
                    f"🎉 NEW REFERRAL!\n\n{user.first_name} joined via your link!\n💰 +₹50 to your balance!"
                )
            except:
                pass
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        f"💰 **Money Bot v6** (Supabase)\n\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n"
        f"👥 Referrals: {stats['referrals']}\n\n"
        f"🚀 Start earning now!",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    if not stats:
        await update.message.reply_text("Please /start first!", reply_markup=create_main_keyboard())
        return
    
    ad_reward = random.randint(3, 5)
    
    # Update user earnings
    increment_field(user_id, 'balance', ad_reward)
    increment_field(user_id, 'total_earnings', ad_reward)
    increment_field(user_id, 'ads_watched', 1)
    
    # Referral commission (5%)
    if stats['referrer_id']:
        commission = ad_reward * 0.05
        increment_field(stats['referrer_id'], 'balance', commission)
        increment_field(stats['referrer_id'], 'commission_earned', commission)
        create_transaction(stats['referrer_id'], 'commission', commission, f"{update.effective_user.first_name} watched ad")
    
    create_transaction(user_id, 'ad', ad_reward, f"Ad reward (₹{ad_reward})")
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"🎉 **Ad Watched Successfully!**\n\n"
        f"💰 **Earned: ₹{ad_reward}**\n"
        f"💵 **New Balance: ₹{stats['balance']:.2f}**\n"
        f"📺 **Total Ads: {stats['ads_watched']}**\n\n"
        f"Watch more ads! 🚀",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"💵 **Your Stats**\n\n"
        f"💰 Balance: `₹{stats['balance']:.2f}`\n"
        f"📺 Ads Watched: `{stats['ads_watched']}`\n"
        f"💸 Total Earnings: `₹{stats['total_earnings']:.2f}`\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
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
            f"✅ Comes back tomorrow at midnight UTC!",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "🎁 **Daily Bonus**\n\n"
            "Already claimed today!\n⏰ Resets at midnight UTC\n\nKeep earning with ads & referrals! 🚀",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )

async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Top 10 by balance
    response = supabase.table('users').select('first_name, balance').order('balance', desc=True).limit(10).execute()
    leaderboard = response.data
    
    msg = "🏆 **TOP 10 Richest Users**\n\n"
    for i, user in enumerate(leaderboard, 1):
        msg += f"{i}. {user['first_name']} - ₹{user['balance']:.2f}\n"
    
    await update.message.reply_text(msg + "\n👆 Be #1! 🚀", parse_mode='Markdown', reply_markup=create_main_keyboard())

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    await update.message.reply_text(
        f"👥 **Refer & Earn**\n\n"
        f"🔗 **Your Link:**\n`{link}`\n\n"
        f"💰 **₹50 per signup**\n"
        f"📈 **5% commission FOREVER** on their ads\n\n"
        f"📊 **Your Stats:**\n"
        f"👥 Referrals: `{stats['referrals']}`\n"
        f"💎 Commission: `₹{stats['commission_earned']:.2f}`",
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💰 Watch Ads":
        await handle_watch_ads(update, context)
    elif text == "💵 Balance":
        await handle_balance(update, context)
    elif text == "👥 Refer and Earn":
        await handle_refer(update, context)
    elif text == "🎁 Bonus":
        await handle_bonus(update, context)
    elif text == "⭐ Leaderboard":
        await handle_leaderboard(update, context)
    elif text == "📊 Stats":
        await handle_balance(update, context)
    else:
        await update.message.reply_text("Use the buttons below 👇", reply_markup=create_main_keyboard())

def main():
    if not all([os.getenv('BOT_TOKEN'), SUPABASE_URL, SUPABASE_ANON_KEY]):
        logger.error("Missing env vars!")
        return
    
    app = Application.builder().token(os.getenv('BOT_TOKEN')).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🤖 Money Bot v6 Started - VPS-PROOF!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
