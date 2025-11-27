import logging
import os
import random
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
import json

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Supabase connection
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE_URL and SUPABASE_ANON_KEY required!")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user(user_id: int):
    """Get or create user"""
    response = supabase.table('users').select('*').eq('id', user_id).execute()
    return response.data[0] if response.data else None

def create_user(user_id: int, first_name: str, username: str = None, referrer_id: int = None):
    """Create new user"""
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
        'referrer_id': referrer_id
    }
    
    supabase.table('users').insert(user_data).execute()
    
    # Reward referrer
    if referrer_id:
        supabase.table('users').update({
            'referrals': supabase.rpc('increment_field', {'user_id': referrer_id, 'field': 'referrals'}),
            'balance': supabase.rpc('increment_field_float', {'user_id': referrer_id, 'field': 'balance', 'amount': 50.0})
        }).eq('id', referrer_id).execute()
        
        # Add transaction
        supabase.table('transactions').insert({
            'user_id': referrer_id,
            'type': 'referral_signup',
            'amount': 50.0,
            'description': f"New referral: {first_name}"
        }).execute()
    
    logger.info(f"Created user {user_id}")

def get_user_stats(user_id: int):
    """Get complete user stats"""
    user = get_user(user_id)
    if user:
        return {
            'balance': user.get('balance', 0),
            'referrals': user.get('referrals', 0),
            'ads_watched': user.get('ads_watched', 0),
            'total_earnings': user.get('total_earnings', 0),
            'commission_earned': user.get('commission_earned', 0),
            'bonus_claimed': user.get('bonus_claimed', False),
            'referrer_id': user.get('referrer_id')
        }
    return {}

def add_balance(user_id: int, amount: float, field: str = 'balance'):
    """Add to user balance/field"""
    supabase.table('users').update({field: supabase.rpc('increment_field_float', {'user_id': user_id, 'field': field, 'amount': amount})}).eq('id', user_id).execute()

def create_transaction(user_id: int, trans_type: str, amount: float, description: str):
    """Log transaction"""
    supabase.table('transactions').insert({
        'user_id': user_id,
        'type': trans_type,
        'amount': amount,
        'description': description
    }).execute()

def can_claim_bonus(user_id: int):
    """Check if user can claim daily bonus (simple - reset daily at midnight UTC)"""
    user = get_user(user_id)
    return user and not user.get('bonus_claimed', False)

def create_main_keyboard():
    keyboard = [
        [KeyboardButton("💰 Watch Ads"), KeyboardButton("💵 Balance")],
        [KeyboardButton("👥 Refer and Earn"), KeyboardButton("🎁 Bonus")],
        [KeyboardButton("⭐ Extra")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Parse referral
    referrer_id = None
    if context.args:
        ref_arg = context.args[0]
        if ref_arg.startswith('ref_'):
            try:
                referrer_id = int(ref_arg[4:])
            except:
                pass
    
    # Get or create user
    existing_user = get_user(user_id)
    if not existing_user:
        create_user(user_id, user.first_name, user.username, referrer_id)
        
        if referrer_id:
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 New Referral!\n\n{user.first_name} joined!\n💰 You earned ₹50\n\nBalance: ₹{get_user_stats(referrer_id)['balance']:.2f}"
                )
            except:
                pass
    
    stats = get_user_stats(user_id)
    
    welcome_message = f"""
👋 Welcome {user.first_name}!

🌟 Money Making Bot (Supabase v5)

💰 Watch Ads: ₹3-5 each
👥 Referrals: ₹50 + 5% commission  
🎁 Daily Bonus: ₹5

💵 Balance: ₹{stats['balance']:.2f}

Start earning! 🚀
    """
    
    await update.message.reply_text(welcome_message, reply_markup=create_main_keyboard())

async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    if not stats:
        await update.message.reply_text("Please /start first!")
        return
    
    ad_reward = random.randint(3, 5)
    
    # Update user
    add_balance(user_id, ad_reward, 'balance')
    add_balance(user_id, ad_reward, 'total_earnings')
    
    # Increment ads watched
    supabase.table('users').update({'ads_watched': supabase.rpc('increment_field', {'user_id': user_id, 'field': 'ads_watched'})}).eq('id', user_id).execute()
    
    # Referral commission
    if stats['referrer_id']:
        commission = ad_reward * 0.05
        add_balance(stats['referrer_id'], commission, 'balance')
        add_balance(stats['referrer_id'], commission, 'commission_earned')
        create_transaction(stats['referrer_id'], 'commission', commission, f"{update.effective_user.first_name} ad commission")
    
    # Log transaction
    create_transaction(user_id, 'ad', ad_reward, f"Ad reward ₹{ad_reward}")
    
    # Update stats
    stats = get_user_stats(user_id)
    
    await update.message.reply_text(
        f"🎉 Ad Watched!\n\n"
        f"💰 Earned: ₹{ad_reward}\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n"
        f"📺 Total: {stats['ads_watched']}\n\n"
        f"Keep watching! 🚀",
        reply_markup=create_main_keyboard()
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_user_stats(update.effective_user.id)
    message = f"""
💵 Your Stats

💰 Balance: ₹{stats['balance']:.2f}
📺 Ads: {stats['ads_watched']}
💸 Earnings: ₹{stats['total_earnings']:.2f}
👥 Referrals: {stats['referrals']}
💎 Commission: ₹{stats['commission_earned']:.2f}
    """
    await update.message.reply_text(message, reply_markup=create_main_keyboard())

async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start=ref_{update.effective_user.id}"
    stats = get_user_stats(update.effective_user.id)
    
    message = f"""
👥 Refer & Earn

🔗 Your Link:
`{referral_link}`

💰 ₹50 per signup
📈 5% commission EVERY ad

📊 Stats:
👥 Referrals: {stats['referrals']}
💎 Commission: ₹{stats['commission_earned']:.2f}

Share everywhere! 🚀
    """
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=create_main_keyboard())

async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not can_claim_bonus(user_id):
        await update.message.reply_text("🎁 Bonus already claimed today!\nTomorrow ⏰", reply_markup=create_main_keyboard())
        return
    
    bonus = 5.0
    add_balance(user_id, bonus, 'balance')
    supabase.table('users').update({'bonus_claimed': True}).eq('id', user_id).execute()
    create_transaction(user_id, 'bonus', bonus, "Daily bonus")
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"🎉 Bonus Claimed!\n\n"
        f"💰 +₹5.00\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n\n"
        f"Tomorrow again! 🌟",
        reply_markup=create_main_keyboard()
    )

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⭐ Extra Features\n\n"
        "• Leaderboard\n"
        "• Withdrawals (soon)\n"
        "• Premium tasks\n\n"
        "Coming soon! 🚀",
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
    elif text == "⭐ Extra":
        await handle_extra(update, context)
    else:
        await update.message.reply_text("Use buttons below 👇", reply_markup=create_main_keyboard())

def main():
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🤖 Supabase Money Bot v5 Started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
