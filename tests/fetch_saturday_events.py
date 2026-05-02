import sys
import io
import os
from dotenv import load_dotenv

# Ensure the root directory is in the path so we can find vspagent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vspagent.tools import MeetupTool

def main():
    # Load environment variables (for OpenAI API key)
    load_dotenv()

    # Fix encoding for Windows console
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=" * 60)
    print("📅  VSP AGENT - SATURDAY EVENT FETCH TEST")
    print("=" * 60)
    
    print("\n🔍 Fetching upcoming Saturday events from Meetup.com...")
    
    try:
        events = MeetupTool.fetch_bangalore_events()
        
        if not events:
            print("\n❌ No Saturday events found or an error occurred.")
            return

        print(f"\n✅ Found {len(events)} events for upcoming Saturdays:\n")
        
        for i, event in enumerate(events, 1):
            print(f"{i}. {event['title']}")
            print(f"   📅 Date: {event['date']}")
            print(f"   🔗 Link: {event['url']}")
            print("-" * 60)

    except Exception as e:
        print(f"\n❌ Error during execution: {e}")

if __name__ == "__main__":
    main()
