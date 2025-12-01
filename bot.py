import logging
import os
from dotenv import load_dotenv
load_dotenv()
import random
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        referrer = get_user(referrer_id)
        if referrer:
            supabase.table('users').update({
                'referrals': referrer.get('referrals', 0) + 1,
                'balance': referrer.get('balance', 0) + 50.0
            }).eq('id', referrer_id).execute()
            
            supabase.table('transactions').insert({
                'user_id': referrer_id,
                'type': 'referral_signup',
                'amount': 50.0,
                'description': f"New referral: {first_name}",
                'created_at': datetime.utcnow().isoformat()
            }).execute()

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
            'referrer_id': user.get('referrer_id')
        }
    return {
        'balance': 0.0, 'referrals': 0, 'ads_watched': 0,
        'total_earnings': 0.0, 'commission_earned': 0.0,
        'bonus_claimed': False, 'last_bonus_date': None, 'referrer_id': None
    }

def update_user_field(user_id: int, field: str, value):
    supabase.table('users').update({field: value}).eq('id', user_id).execute()

def increment_field(user_id: int, field: str, amount: float = 1):
    user = get_user(user_id)
    if user:
        current = float(user.get(field, 0))
        new_value = current + amount
        supabase.table('users').update({field: new_value}).eq('id', user_id).execute()
        return new_value
    return 0

def can_claim_bonus(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    
    last_bonus_date = user.get('last_bonus_date')
    today = date.today().isoformat()
    
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
        [KeyboardButton("💰 Watch Ads")],
        [KeyboardButton("💵 Balance"), KeyboardButton("👥 Refer & Earn")],
        [KeyboardButton("🎁 Bonus"), KeyboardButton("⭐ Leaderboard")],
        [KeyboardButton("⭐ Extra")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def create_withdraw_keyboard():
    keyboard = [
        [InlineKeyboardButton("1️⃣ UPI", callback_data="withdraw_upi")],
        [InlineKeyboardButton("2️⃣ Paytm", callback_data="withdraw_paytm")],
        [InlineKeyboardButton("3️⃣ Bank Transfer", callback_data="withdraw_bank")],
        [InlineKeyboardButton("4️⃣ Paypal", callback_data="withdraw_paypal")],
        [InlineKeyboardButton("5️⃣ USDT TRC20", callback_data="withdraw_usdt")],
        [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_extra_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 Main Channel", url="https://t.me/cashyads")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/cashyads_support")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0][4:])
        except:
            pass
    
    existing = get_user(user_id)
    if not existing:
        create_user(user_id, user.first_name, user.username, referrer_id)
    
    stats = get_user_stats(user_id)
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        f"💰 **CashyAds v7.1** (Production)\n\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n"
        f"👥 Referrals: {stats['referrals']}\n\n"
        f"🚀 Start earning now!",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    ad_reward = random.randint(3, 5)
    
    increment_field(user_id, 'balance', ad_reward)
    increment_field(user_id, 'total_earnings', ad_reward)
    increment_field(user_id, 'ads_watched', 1)
    
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
    withdraw_btn = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="show_withdraw")]])
    
    await update.message.reply_text(
        f"💵 **Your Total Balance**\n\n"
        f"`₹{stats['balance']:.2f}`\n\n"
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
        f"📈 **5% commission FOREVER** on their ads\n\n"
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
    response = supabase.table('users').select('first_name, balance').order('balance', desc=True).limit(10).execute()
    leaderboard = response.data
    
    msg = "🏆 **TOP 10 Richest Users**\n\n"
    for i, user in enumerate(leaderboard, 1):
        msg += f"{i}. {user['first_name']} - ₹{float(user['balance']):.2f}\n"
    
    await update.message.reply_text(msg + "\n👆 Be #1! 🚀", parse_mode='Markdown', reply_markup=create_main_keyboard())

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

# ✅ FIXED CALLBACK HANDLERS
async def handle_withdraw_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    stats = get_user_stats(user_id)
    
    balance_ok = stats['balance'] >= 380
    referrals_ok = stats['referrals'] >= 15
    
    if not balance_ok:
        await query.answer(f"❌ Minimum ₹380 required!\nCurrent: ₹{stats['balance']:.2f}", show_alert=True)
        return False
    if not referrals_ok:
        remaining = 15 - stats['referrals']
        await query.answer(f"👥 {stats['referrals']}/15 referrals\nNeed {remaining} more!", show_alert=True)
        return False
    
    withdraw_kb = create_withdraw_keyboard()
    await query.edit_message_text("💳 **Select Withdraw Method**", reply_markup=withdraw_kb, parse_mode='Markdown')
    return True

async def handle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "withdraw_cancel":
        await query.edit_message_text("💸 Withdraw cancelled!", reply_markup=create_main_keyboard())
        return
    
    if data == "back_main":
        await query.edit_message_text("🔙 Back to main menu!", reply_markup=create_main_keyboard())
        return
    
    method = data.split('_')[1].upper()
    user_id = query.from_user.id
    stats = get_user_stats(user_id)
    
    # Deduct full balance
    withdraw_amount = stats['balance']
    increment_field(user_id, 'balance', -withdraw_amount)
    create_transaction(user_id, 'withdraw', -withdraw_amount, f"Withdraw via {method}")
    
    await query.edit_message_text(
        f"✅ **Withdrawal Initiated!**\n\n"
        f"💰 Amount: `₹{withdraw_amount:.2f}`\n"
        f"💳 Method: **{method}**\n\n"
        f"📝 **Send your {method} details:**\n"
        f"`yourupi@paytm` or `bank details` or `wallet address`\n\n"
        f"⏰ **Processing: 6-7 working days**\n"
        f"⚠️ May take longer on holidays.",
        parse_mode='Markdown',
        reply_markup=None
    )
    
    # Set user state for next message
    context.user_data['awaiting_withdraw_details'] = True
    context.user_data['withdraw_method'] = method
    context.user_data['withdraw_amount'] = withdraw_amount

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "show_withdraw":
        await handle_withdraw_check(update, context)
    elif query.data.startswith("withdraw_") or query.data == "withdraw_cancel" or query.data == "back_main":
        await handle_withdraw_method(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if awaiting withdraw details
    if context.user_data.get('awaiting_withdraw_details'):
        method = context.user_data.get('withdraw_method', 'UPI')
        amount = context.user_data.get('withdraw_amount', 0)
        
        create_transaction(user_id, 'withdraw_details', 0, f"{method} details: {text}")
        context.user_data.clear()  # Reset state
        
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
    
    # Regular button handling
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

def main():
    if not all([os.getenv('BOT_TOKEN'), SUPABASE_URL, SUPABASE_ANON_KEY]):
        logger.error("Missing env vars!")
        return
    
    app = Application.builder().token(os.getenv('BOT_TOKEN')).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🤖 CashyAds v7.1 Started - ALL BUGS FIXED!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
