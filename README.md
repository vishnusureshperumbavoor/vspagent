# 🤖 VSP Agent

[![PyPI version](https://badge.fury.io/py/vspagent.svg)](https://pypi.org/project/vspagent/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vspagent.svg)](https://pypi.org/project/vspagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AI-powered chat agent about Vishnu Suresh Perumbavoor. Powered by Qwen2.5-0.5B.**

## 🚀 Features

- 🧠 **AI Chat**: Interactive conversations powered by Qwen2.5-0.5B language model
- 🧠 **Conversation Memory**: Maintains context throughout the chat session
- ⚡ **GPU Acceleration**: Automatic GPU support for 30-50x faster responses
- 🎯 **CLI Interface**: Easy-to-use command-line interface

## 📦 Installation

### From PyPI
```bash
pip install vspagent
```

### Local Development
If you want to run the agent from source:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

## 🎯 Quick Start

### CLI Mode

Simply run:

```bash
vspagent-py
```

This launches an **interactive chat session** with the VSP Agent!

**Example Chat Session:**
```
💬 You: Who is VSP?
🤖 VSP Agent: VSP stands for Vishnu Suresh Perumbavoor. He is the founder 
of VSP Enterprises and VSP Intelligence. He's a Software Engineer, Singer, 
and YouTuber...

💬 You: What technologies does he use?
🤖 VSP Agent: He works with React, Node.js, FastAPI, Docker, MongoDB...

💬 You: What has he accomplished?
🤖 VSP Agent: He won 3rd prize in Vaiga Agrihack 2023...

💬 You: exit
👋 Thanks for chatting!
```

**Features:**
- 🤖 AI-powered conversations with Qwen2.5-0.5B
- 💬 Natural language understanding
- 🧠 Conversation memory (maintains context)
- ⚡ GPU acceleration (30-50x faster if available)
- 🎯 Simple and focused on chatting about VSP

**Note:** Command is `vspagent-py` (not `vspagent`) to avoid conflicts with the JavaScript version.

### Python API

```python
from vspagent import VSPAgent, biodata

# Create agent instance
agent = VSPAgent()

# Initialize AI model (loads Qwen2.5-0.5B)
agent.init_ai()

# Chat with the agent
response = agent.chat("Who is VSP?")
print(response)

# Continue conversation with context
conversation_history = []
conversation_history.append({"role": "user", "content": "Who is VSP?"})
conversation_history.append({"role": "assistant", "content": response})

response2 = agent.chat("What technologies does he use?", conversation_history)
print(response2)

# Access biodata directly
print(biodata['creator'])
print(biodata['technologies'])
```

## 📚 API Reference

### `VSPAgent` Class

#### Methods

- **`init_ai()`**: Initialize the Qwen2.5-0.5B AI model (required before chatting)
- **`chat(message, conversation_history=None)`**: Chat with the AI agent
  - `message` (str): Your question or message
  - `conversation_history` (list, optional): Previous conversation for context
  - Returns: AI-generated response as string

### `biodata` Dictionary

Contains comprehensive information about Vishnu Suresh Perumbavoor:
- Personal information
- Founder companies
- Technologies and skills
- Accomplishments
- Social media links

## 🛠️ Requirements

- Python 3.8+
- transformers >= 4.30.0
- torch >= 2.0.0

## 🎨 Using the CLI

When running `vspagent-py`:
- Simply type your questions or messages
- The AI will respond with information about VSP
- Type `exit` or `quit` to end the conversation
- Conversation context is maintained throughout the session

## 👨‍💻 About VSP

**Vishnu Suresh Perumbavoor** is the founder of VSP Enterprises and VSP Intelligence. He's a:
- Software Engineer
- Singer
- YouTuber
- Technology enthusiast

### 🏆 Accomplishments
- Won 3rd prize in Vaiga Agrihack 2023
- Participated in Rajasthan IT Hackathon 2023
- Won 1st prize in startup idea presentation at Palakkad

### 🔧 Technologies
React, Node.js, FastAPI, Express, MongoDB, Docker, OHIF, Cornerstone3D, VTKjs, DICOM

## 🔗 Connect

- 💼 [LinkedIn](https://www.linkedin.com/in/vishnu-suresh-perumbavoor/)
- 🐙 [GitHub](https://github.com/vishnusureshperumbavoor)
- 🐦 [Twitter](https://twitter.com/vspeeeeee)
- 📺 [YouTube](https://www.youtube.com/@vishnusureshperumbavoor/videos)
- 📷 [Instagram](https://www.instagram.com/vishnusureshperumbavoor/)

## 📄 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🐛 Issues

Found a bug? [Report it here](https://github.com/vishnusureshperumbavoor/vsp_bot/issues)

## 📈 Version

Current version: **2.2.0**

---

Made with ❤️ by Vishnu Suresh Perumbavoor

