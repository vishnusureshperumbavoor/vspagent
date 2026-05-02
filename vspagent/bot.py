import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from .tools import MeetupTool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_text = (
        f"Hi {user.first_name}! 👋\n\n"
        "I am your **VSP Saturday Event Planner**.\n"
        "I can help you find upcoming tech and community events in Bangalore happening on Saturdays.\n\n"
        "Type /events to see what's happening this weekend!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def fetch_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch Saturday events and send them to the user."""
    query = update.message if update.message else update.callback_query.message
    
    status_msg = await query.reply_text("🔍 Searching Meetup.com for Saturday events in Bangalore...")
    
    try:
        events = MeetupTool.fetch_bangalore_events()
        
        if not events:
            await status_msg.edit_text("❌ No Saturday events found right now. Check back later!")
            return

        response_text = f"✅ **Found {len(events)} events for upcoming Saturdays:**\n\n"
        
        for i, event in enumerate(events, 1):
            response_text += f"{i}. **[{event['title']}]({event['url']})**\n"
            response_text += f"   📅 {event['date']}\n\n"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown', disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ Error fetching events: {str(e)}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    application = ApplicationBuilder().token(token).build()
    
    start_handler = CommandHandler('start', start)
    events_handler = CommandHandler('events', fetch_events)
    
    application.add_handler(start_handler)
    application.add_handler(events_handler)
    
    print("🚀 VSP Telegram Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
