"""VSP Agent - Tools for agentic capabilities"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
from typing import List, Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class MeetupTool:
    """Tool for fetching events from Meetup.com using AI parsing and NEXT_DATA"""
    
    @staticmethod
    def fetch_bangalore_events() -> List[Dict]:
        """Fetch upcoming events in Bengaluru from Meetup.com"""
        url = "https://www.meetup.com/find/in--bangalore/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Try to find __NEXT_DATA__ (Very reliable for Meetup)
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    props = data.get('props', {}).get('pageProps', {})
                    # Try different potential keys where Meetup stores events
                    raw_events = props.get('eventsInLocation') or props.get('todayEvents') or []
                    
                    if raw_events:
                        events = []
                        for item in raw_events:
                            if isinstance(item, dict):
                                title = item.get('title')
                                url_path = item.get('eventUrl')
                                date_str = item.get('dateTime', 'Upcoming')
                                
                                if title and url_path:
                                    events.append({
                                        "title": title,
                                        "date": date_str,
                                        "url": url_path if url_path.startswith('http') else f"https://www.meetup.com{url_path}"
                                    })
                        if events:
                            return events[:10]
                except Exception as e:
                    pass

            # 2. AI Parsing Fallback (Robust if NEXT_DATA fails)
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return []

            client = OpenAI(api_key=api_key)
            
            # Clean HTML aggressively to save tokens
            for tag in soup(["script", "style", "nav", "footer", "svg", "img", "path"]):
                tag.decompose()
            
            # Extract only links and headers as they contain the core event info
            relevant_elements = soup.find_all(['a', 'h3', 'h4', 'span'])
            clean_lines = []
            for el in relevant_elements:
                text = el.get_text(strip=True)
                if len(text) > 5: # Skip tiny snippets
                    clean_lines.append(text)
            
            body_text = "\n".join(clean_lines)
            body_text = body_text[:6000] # Reduced from 15000 to save tokens

            prompt = f"""Extract upcoming events from this text from Meetup.com Bangalore. 
Return ONLY a JSON list of objects with "title", "date", and "url".

Text:
{body_text}
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are a concise data extractor. Output JSON only."},
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            # Find the first list in the response
            events = []
            for val in result.values():
                if isinstance(val, list):
                    events = val
                    break
            
            if isinstance(events, list):
                return events[:10]
            
            return []
            
        except Exception as e:
            print(f"Error fetching Meetup events: {e}")
            return []

def get_tools_info():
    """Return info about available tools"""
    return {
        "meetup_events": {
            "description": "Finds upcoming events in Bangalore from Meetup.com",
            "function": MeetupTool.fetch_bangalore_events
        }
    }
