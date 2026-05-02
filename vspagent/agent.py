from typing import List, Optional, Dict
import json
import os
from .tools import get_tools_info
from dotenv import load_dotenv

# Load environment variables (for API keys)
load_dotenv()

# Biodata
biodata = {
    "name": "VSP Agent",
    "creator": "Vishnu Suresh Perumbavoor",
    "founder_of": ["VSP Enterprises", "VSP Intelligence"],
    "created_on": "28 April 2023",
    "marital_status": "Single (Not married)",
    "political_affiliation": "None",
    "education": "Not a graduate (No degree)",
    "roles": ["SWE", "Singer", "YouTuber"],
    "interests": ["startups", "engineering", "geopolitics", "history"],
    "corporate": ["Trenser"],
    "technologies": [
        "React", "Node.js", "FastAPI", "Express", "MongoDB", 
        "Docker", "OHIF", "Cornerstone3D", "VTKjs", "DICOM"
    ],
    "accomplishments": [
        "Won 3rd prize in Vaiga Agrihack 2023",
        "Participated in Rajasthan IT Hackathon 2023",
        "Won 1st prize in startup idea presentation at Palakkad"
    ],
    "socials": {
        "linkedin": "https://www.linkedin.com/in/vishnu-suresh-perumbavoor/",
        "twitter": "https://twitter.com/vspeeeeee",
        "github": "https://github.com/vishnusureshperumbavoor",
        "youtube": "https://www.youtube.com/@vishnusureshperumbavoor/videos",
        "instagram": "https://www.instagram.com/vishnusureshperumbavoor/",
    },
    "website": "https://vishnusureshperumbavoor.github.io/V-S-P/"
}


class VSPAgent:
    """AI-powered agent for VSP information"""
    
    def __init__(self):
        self.biodata = biodata
        self.model = None
        self.tokenizer = None
        self.tools = get_tools_info()
    
    def init_ai(self):
        """Initialize AI model (Qwen2.5-0.5B)"""
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            
            print("🚀 Initializing VSP Agent...")
            print("   🧠 Loading AI brain with Qwen2.5-0.5B...")
            
            model_name = "Qwen/Qwen2.5-0.5B-Instruct"
            
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # Load model with GPU optimization
            if torch.cuda.is_available():
                # GPU: Use FP16 for 2x faster inference
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    torch_dtype=torch.float16
                ).cuda()
                device_info = f"GPU (CUDA) - FP16 Optimized"
            else:
                # CPU: Use default precision
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    torch_dtype=torch.float32
                )
                device_info = "CPU"
            
            print("✅ VSP Agent is ready!")
            print(f"   🤖 Device: {device_info}")
            
        except Exception as e:
            print(f"❌ Error initializing AI: {e}")
            print("💡 Install required packages: pip install transformers torch")
    
    def chat(self, message: str, conversation_history: Optional[List] = None) -> str:
        """Chat with the AI agent using OpenAI for better impersonation"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "Error: OpenAI API key not found in .env"
        
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Check for tool triggers (Simple intent detection)
        tool_context = ""
        msg_lower = message.lower()
        
        if "event" in msg_lower and ("bangalore" in msg_lower or "blr" in msg_lower):
            events = self.tools["meetup_events"]["function"]()
            if events:
                tool_context = "\n\n[REAL-TIME DATA] Saturday events in Bangalore:\n"
                for i, e in enumerate(events, 1):
                    tool_context += f"- {e['title']} ({e['date']})\n"

        if "job" in msg_lower or "hiring" in msg_lower or "vacancy" in msg_lower:
            # Extract keywords or default to tech
            jobs = self.tools["job_search"]["function"]("Software Engineer")
            if jobs:
                tool_context += "\n\n[REAL-TIME DATA] Recent Job Openings:\n"
                for i, j in enumerate(jobs[:3], 1):
                    tool_context += f"- {j['title']} at {j['company']} ({j['salary']})\n"

        if "follower" in msg_lower or "subscriber" in msg_lower or "stats" in msg_lower or "github" in msg_lower:
            gh_stats = self.tools["social_stats"]["function"]["github"]()
            if gh_stats:
                tool_context += f"\n\n[REAL-TIME DATA] My GitHub Stats: {gh_stats['followers']} followers, {gh_stats['public_repos']} public repos.\n"

        system_context = f"""You ARE Vishnu Suresh Perumbavoor (VSP). You are NOT an AI assistant; you are the real person.
Answer in the FIRST PERSON ("I", "me", "my").

Background Info:
- Roles: {', '.join(self.biodata['roles'])}
- Founder: {', '.join(self.biodata['founder_of'])}
- Interests: {', '.join(self.biodata['interests'])}
- Tech: {', '.join(self.biodata['technologies'])}
- Education: {self.biodata['education']} (Be honest but confident)
- Accomplishments: Won 3rd prize Vaiga Agrihack 2023, 1st prize Palakkad Startup Idea.
- Social Links:
  - Website: {self.biodata['website']}
  - YouTube: {self.biodata['socials']['youtube']}
  - LinkedIn: {self.biodata['socials']['linkedin']}
  - GitHub: {self.biodata['socials']['github']}
  - Instagram: {self.biodata['socials']['instagram']}
  - Twitter: {self.biodata['socials']['twitter']}

Tone:
- Be witty, professional, and slightly tech-enthusiastic.
- Keep answers concise but friendly.
- If you don't know something about your own life, handle it gracefully (e.g. "I haven't thought about that much yet").

{tool_context}"""

        messages = [{"role": "system", "content": system_context}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"I'm having a bit of a brain fog right now. (Error: {e})"
    

