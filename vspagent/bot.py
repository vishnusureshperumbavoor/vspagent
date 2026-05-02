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
        "Type /events to see what's happening this weekend!\n"
        "Type /jobs <keyword> to search for job opportunities in Bangalore."
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

async def search_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for jobs and send them to the user."""
    query_text = " ".join(context.args)
    if not query_text:
        await update.message.reply_text("Please provide a job title. Example: `/jobs Python Developer`", parse_mode='Markdown')
        return

    status_msg = await update.message.reply_text(f"🔍 Searching for '{query_text}' jobs in Bangalore...")
    
    try:
        from .tools import JobSearchTool
        jobs = JobSearchTool.search_jobs(query_text)
        
        if not jobs:
            await status_msg.edit_text(f"❌ No '{query_text}' jobs found in Bangalore right now.")
            return

        response_text = f"💼 **Found {len(jobs)} job opportunities:**\n\n"
        
        for i, job in enumerate(jobs, 1):
            response_text += f"{i}. **[{job['title']}]({job['url']})**\n"
            response_text += f"   🏢 {job['company']}\n"
            response_text += f"   💰 {job['salary']}\n"
            if job['description']:
                # Simple cleanup of HTML tags if any
                clean_desc = job['description'].replace('<b>', '').replace('</b>', '').replace('...', '')
                response_text += f"   📝 _{clean_desc}_\n"
            response_text += "\n"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown', disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ Error fetching jobs: {str(e)}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    application = ApplicationBuilder().token(token).build()
    
    start_handler = CommandHandler('start', start)
    events_handler = CommandHandler('events', fetch_events)
    jobs_handler = CommandHandler('jobs', search_jobs)
    
    application.add_handler(start_handler)
    application.add_handler(events_handler)
    application.add_handler(jobs_handler)
    
    print("🚀 VSP Telegram Agent is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
