"""VSP Agent - Tools for agentic capabilities"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
from typing import List, Dict, Optional
from datetime import datetime
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
                                    # Filter for Saturdays only
                                    is_saturday = False
                                    formatted_date = date_str
                                    try:
                                        # Meetup date format: 2026-05-09T09:30:00+05:30
                                        dt = datetime.fromisoformat(date_str)
                                        if dt.weekday() == 5: # 5 is Saturday
                                            is_saturday = True
                                            # Format to DD Month YYYY HH:MMAM/PM
                                            formatted_date = dt.strftime('%d %b %Y %I:%M%p')
                                    except:
                                        # Fallback: simple text check if parsing fails
                                        if "sat" in date_str.lower():
                                            is_saturday = True
                                    
                                    if is_saturday:
                                        events.append({
                                            "title": title,
                                            "date": formatted_date,
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
ONLY include events that are happening on a SATURDAY.
Return ONLY a JSON list of objects with "title", "date", and "url".
Format the "date" as DD Month YYYY HOURS:MINAM/PM (e.g., 09 May 2026 09:30AM).

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

class JobSearchTool:
    """Tool for fetching job listings from Adzuna API"""
    
    @staticmethod
    def search_jobs(query: str, location: str = "Bangalore") -> List[Dict]:
        """Search for jobs using Adzuna API"""
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_API_KEY") # Matching your .env name
        
        if not app_id or not app_key:
            print("Error: Adzuna credentials not found in .env")
            return []

        # Adzuna API for India (in)
        url = f"https://api.adzuna.com/v1/api/jobs/in/search/1"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 5,
            "what": query,
            "where": location,
            "content-type": "application/json"
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            jobs = []
            for result in data.get('results', []):
                jobs.append({
                    "title": result.get('title'),
                    "company": result.get('company', {}).get('display_name'),
                    "location": result.get('location', {}).get('display_name'),
                    "salary": f"₹{result.get('salary_min')}" if result.get('salary_min') else "Not disclosed",
                    "url": result.get('redirect_url'),
                    "description": result.get('description', '')[:200]
                })
            return jobs
        except Exception as e:
            print(f"Error fetching jobs: {e}")
            return []

class SocialStatsTool:
    """Tool for fetching live social media statistics"""
    
    @staticmethod
    def get_github_stats(username: str = "vishnusureshperumbavoor") -> Dict:
        """Fetch follower count from GitHub API"""
        url = f"https://api.github.com/users/{username}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {"followers": data.get("followers", 0), "public_repos": data.get("public_repos", 0)}
            return {}
        except: return {}

def get_tools_info():
    """Return info about available tools"""
    return {
        "meetup_events": {
            "description": "Finds upcoming events in Bangalore from Meetup.com",
            "function": MeetupTool.fetch_bangalore_events
        },
        "job_search": {
            "description": "Searches for job listings in India",
            "function": JobSearchTool.search_jobs
        },
        "social_stats": {
            "description": "Fetches live follower counts",
            "function": {
                "github": SocialStatsTool.get_github_stats
            }
        }
    }
