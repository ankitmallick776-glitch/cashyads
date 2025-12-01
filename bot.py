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

# ... [same database functions as before until create_main_keyboard] ...

def create_main_keyboard():
    """5 Button Layout as requested"""
    keyboard = [
        [KeyboardButton("💰 Watch Ads")],  # Row 1: Single button
        [KeyboardButton("💵 Balance"), KeyboardButton("👥 Refer & Earn")],  # Row 2: 2 buttons
        [KeyboardButton("🎁 Bonus"), KeyboardButton("⭐ Leaderboard")],  # Row 3: 2 buttons
        [KeyboardButton("⭐ Extra")]  # Row 4: Single button
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def create_withdraw_keyboard():
    """Withdraw method inline buttons"""
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
    """Extra menu inline buttons"""
    keyboard = [
        [InlineKeyboardButton("📢 Main Channel", url="https://t.me/your_channel")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/your_support")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="extra_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ... [same get_user, get_user_stats, increment_field, can_claim_bonus functions] ...

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
        f"💰 **CashyAds v7** (Production)\n\n"
        f"💵 Balance: ₹{stats['balance']:.2f}\n"
        f"👥 Referrals: {stats['referrals']}\n\n"
        f"🚀 Start earning now!",
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Balance with Withdraw button"""
    stats = get_user_stats(update.effective_user.id)
    withdraw_btn = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="show_withdraw")]])
    
    await update.message.reply_text(
        f"💵 **Your Total Balance**\n\n"
        f"`₹{stats['balance']:.2f}`\n\n"
        f"💰 Click Withdraw to cash out!",
        reply_markup=withdraw_btn,
        parse_mode='Markdown'
    )

async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extra menu with stats + inline buttons"""
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
    """Check withdraw eligibility"""
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    
    balance_ok = stats['balance'] >= 380
    referrals_ok = stats['referrals'] >= 15
    
    if not balance_ok:
        await update.callback_query.answer(f"Minimum ₹380 required!", show_alert=True)
        return
    if not referrals_ok:
        remaining = 15 - stats['referrals']
        await update.callback_query.answer(f"{stats['referrals']}/15 referrals done!\nNeed {remaining} more friends!", show_alert=True)
        return
    
    # Both checks passed - ask for payment method
    withdraw_kb = create_withdraw_keyboard()
    await update.callback_query.edit_message_text(
        "💳 **Select Withdraw Method**",
        reply_markup=withdraw_kb,
        parse_mode='Markdown'
    )

async def handle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle withdraw method selection"""
    query = update.callback_query
    method = query.data.split('_')[1]
    user_id = query.from_user.id
    stats = get_user_stats(user_id)
    
    if query.data == "withdraw_cancel":
        await query.edit_message_text("💸 Withdraw cancelled!", reply_markup=create_main_keyboard())
        return
    
    await query.answer()
    
    # Deduct balance (simulate withdraw)
    increment_field(user_id, 'balance', -stats['balance'])
    create_transaction(user_id, 'withdraw', -stats['balance'], f"Withdraw via {method.upper()}")
    
    await query.edit_message_text(
        f"✅ **Withdrawal Successful!**\n\n"
        f"💰 Amount: `₹{stats['balance']:.2f}`\n"
        f"💳 Method: **{method.upper()}**\n\n"
        f"📋 **Type your {method.upper()} details correctly:**\n"
        f"`yourupi@paytm` or `bank details` or `wallet address`\n\n"
        f"⏰ You will get your money **within 6-7 working days**.\n"
        f"⚠️ Note: Might take longer if holiday.",
        parse_mode='Markdown',
        reply_markup=None
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
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
        # Handle withdraw details sent by user
        user_id = update.effective_user.id
        stats = get_user_stats(user_id)
        if stats['balance'] < 380:
            await update.message.reply_text("Use buttons below 👇", reply_markup=create_main_keyboard())
            return
            
        create_transaction(user_id, 'withdraw_details', 0, f"Details: {text}")
        await update.message.reply_text(
            f"📝 **Withdraw details received!**\n\n"
            f"✅ Your withdrawal is **successful**!\n"
            f"💰 Amount: ₹{stats['balance']:.2f}\n"
            f"⏰ Processing within **6-7 working days**.\n\n"
            f"Keep earning! 🚀",
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        # Reset balance to 0 (already deducted)
        update_user_field(user_id, 'balance', 0)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "show_withdraw":
        await handle_withdraw_check(update, context)
    elif query.data == "extra_back":
        await query.edit_message_text("⭐ Extra menu closed!", reply_markup=create_main_keyboard())
    elif query.data.startswith("withdraw_"):
        await handle_withdraw_method(update, context)

# ... [keep all other functions: handle_watch_ads, handle_bonus, etc. exactly same] ...

def main():
    if not all([os.getenv('BOT_TOKEN'), SUPABASE_URL, SUPABASE_ANON_KEY]):
        logger.error("Missing env vars!")
        return
    
    app = Application.builder().token(os.getenv('BOT_TOKEN')).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🤖 CashyAds v7 Started - 5 BUTTONS + WITHDRAW!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
