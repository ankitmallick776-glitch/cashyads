import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store user data (in production, use a database)
user_data = {}

# Initialize user data
def init_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            'balance': 0,
            'referrals': 0,
            'bonus_claimed': False,
            'ads_watched': 0
        }

# Create keyboard
def create_main_keyboard():
    keyboard = [
        [KeyboardButton("💰 Watch Ads"), KeyboardButton("💵 Balance")],
        [KeyboardButton("👥 Refer and Earn"), KeyboardButton("🎁 Bonus")],
        [KeyboardButton("⭐ Extra")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    
    welcome_message = f"""
👋 Welcome to Money Making Bot, {user.first_name}!

🌟 Start earning money with simple tasks!

Here's what you can do:
💰 Watch Ads - Earn money by watching advertisements
💵 Balance - Check your current earnings
👥 Refer and Earn - Invite friends and earn rewards
🎁 Bonus - Claim your daily bonus
⭐ Extra - Additional features and rewards

Use the buttons below to get started! 🚀
    """
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=create_main_keyboard()
    )

# Handle button presses
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    init_user(user_id)
    
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
        await update.message.reply_text(
            "Please use the buttons below to navigate! 👇",
            reply_markup=create_main_keyboard()
        )

# Watch Ads handler (placeholder)
async def handle_watch_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Watch Ads Feature\n\n"
        "This feature will be configured next.\n"
        "You'll be able to watch ads and earn money!",
        reply_markup=create_main_keyboard()
    )

# Balance handler
async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = user_data[user_id]['balance']
    ads_watched = user_data[user_id]['ads_watched']
    referrals = user_data[user_id]['referrals']
    
    balance_message = f"""
💵 Your Balance

💰 Current Balance: ${balance:.2f}
📺 Ads Watched: {ads_watched}
👥 Referrals: {referrals}

Keep earning by watching ads and referring friends! 🚀
    """
    
    await update.message.reply_text(
        balance_message,
        reply_markup=create_main_keyboard()
    )

# Refer and Earn handler
async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    refer_message = f"""
👥 Refer and Earn

Share your referral link with friends and earn rewards!

🔗 Your Referral Link:
{referral_link}

💰 Earn $1.00 for each friend who joins!

Total Referrals: {user_data[user_id]['referrals']}
    """
    
    await update.message.reply_text(
        refer_message,
        reply_markup=create_main_keyboard()
    )

# Bonus handler
async def handle_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_data[user_id]['bonus_claimed']:
        await update.message.reply_text(
            "🎁 Daily Bonus\n\n"
            "You've already claimed your bonus today!\n"
            "Come back tomorrow for another bonus! ⏰",
            reply_markup=create_main_keyboard()
        )
    else:
        bonus_amount = 0.50
        user_data[user_id]['balance'] += bonus_amount
        user_data[user_id]['bonus_claimed'] = True
        
        await update.message.reply_text(
            f"🎉 Congratulations!\n\n"
            f"You've claimed your daily bonus of ${bonus_amount:.2f}!\n"
            f"New Balance: ${user_data[user_id]['balance']:.2f}\n\n"
            f"Come back tomorrow for more! 🌟",
            reply_markup=create_main_keyboard()
        )

# Extra handler
async def handle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⭐ Extra Features\n\n"
        "This section will contain additional features:\n"
        "• Special offers\n"
        "• Premium tasks\n"
        "• Leaderboard\n"
        "• Achievements\n\n"
        "Coming soon! 🚀",
        reply_markup=create_main_keyboard()
    )

# Main function
def main():
    # Get bot token from environment variable
    TOKEN = os.getenv('BOT_TOKEN')
    
    if not TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start the bot
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
