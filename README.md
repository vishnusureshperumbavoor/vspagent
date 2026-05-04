# 🤖 VSP Digital Twin

[![PyPI version](https://badge.fury.io/py/vspagent.svg)](https://pypi.org/project/vspagent/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vspagent.svg)](https://pypi.org/project/vspagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Advanced AI-powered Digital Twin of Vishnu Suresh Perumbavoor. Now with agentic capabilities, Telegram integration, and GPT-4o-mini impersonation.**

---

## 🚀 Features

- 🧠 **High-Fidelity Impersonation**: Powered by OpenAI's `gpt-4o-mini` for witty, first-person conversations that feel like the real VSP.
- 🤖 **Telegram Bot**: Integrated Saturday Event Planner and Job Searcher directly on Telegram.
- 🛠️ **Agentic Tools**:
  - 📅 **Meetup Scraper**: Real-time Saturday event discovery in Bangalore with AI-powered HTML parsing.
  - 💼 **Job Searcher**: Live job listings from India using the Adzuna API.
  - 📊 **Social Stats**: Live follower and repository counts from GitHub.
- 🧠 **Local Brain Fallback**: Still supports local Qwen2.5-0.5B inference with GPU acceleration.
- 🎯 **CLI Interface**: Interactive terminal-based chat with real-time tool execution indicators.

---

## 📦 Installation

### From PyPI
```bash
pip install vspagent
```

### From Source
```bash
# Clone the repository
git clone https://github.com/vishnusureshperumbavoor/vsp_bot.git
cd vsp_bot

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows

# Install dependencies
pip install -r requirements.txt
```

### ⚙️ Environment Setup
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_openai_key
TELEGRAM_BOT_TOKEN=your_bot_token
ADZUNA_APP_ID=your_adzuna_id
ADZUNA_API_KEY=your_adzuna_key
```

---

## 📱 Telegram Bot Mode

The VSP Digital Twin can run as a Telegram bot to help you plan your weekends!

**To start the bot:**
```bash
python -m vspagent.bot
```

**Commands:**
- `/start`: Introduction to the VSP Saturday Event Planner.
- `/events`: Fetches upcoming Saturday events in Bangalore.
- `/jobs <keyword>`: Searches for job opportunities in Bangalore.
- `[Text]`: Any other message will trigger a chat session with the VSP Digital Twin.

---

## 🎯 Quick Start (CLI)

Launch an interactive session with the digital twin:

```bash
vspagent-py
```

**Example Session:**
```
💬 You: Any tech events this Saturday?
🔍 Searching Meetup.com for events in Bangalore...
🤖 VSP Agent: I found 5 events for this Saturday! There's a "GenAI Workshop" at Indiranagar 
and a "React Meetup" in Koramangala. Which one sounds like your vibe?

💬 You: What's your GitHub status?
🤖 VSP Agent: I'm currently sitting at 124 followers and 42 public repos. 
Feel free to check out my latest projects!
```

---

## 📚 API Reference

### `VSPAgent` Class

```python
from vspagent import VSPAgent

agent = VSPAgent()
# No need to call init_ai() if only using OpenAI-based chat
response = agent.chat("What are you working on lately?")
print(response)
```

### `tools` Module

- `MeetupTool.fetch_bangalore_events()`: Returns Saturday events list.
- `JobSearchTool.search_jobs(query)`: Returns job listings.
- `SocialStatsTool.get_github_stats()`: Returns live follower counts.

---

## 👨‍💻 About VSP

**Vishnu Suresh Perumbavoor** is a Software Engineer, Singer, and YouTuber. He is the founder of **VSP Enterprises** and **VSP Intelligence**.

### 🏆 Accomplishments
- Won 3rd prize in Vaiga Agrihack 2023
- Participated in Rajasthan IT Hackathon 2023
- Won 1st prize in startup idea presentation at Palakkad

### 🔧 Tech Stack
React, Node.js, FastAPI, Docker, OHIF, Cornerstone3D, VTKjs, DICOM

---

## 🔗 Connect

- 💼 [LinkedIn](https://www.linkedin.com/in/vishnu-suresh-perumbavoor/)
- 🐙 [GitHub](https://github.com/vishnusureshperumbavoor)
- 🐦 [Twitter](https://twitter.com/vspeeeeee)
- 📺 [YouTube](https://www.youtube.com/@vishnusureshperumbavoor/videos)
- 📷 [Instagram](https://www.instagram.com/vishnusureshperumbavoor/)

---

## 📄 License

MIT License - see LICENSE file for details

---

Current version: **2.2.0** | Made with ❤️ by Vishnu Suresh Perumbavoor
