from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import os
from .tools import MeetupTool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="VSP Saturday Event Planner")

# Mount static files (if any)
# app.mount("/static", StaticFiles(directory="vspagent/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # We'll serve the HTML directly for simplicity in this single-file server
    # or read it from a file
    try:
        with open("vspagent/static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Frontend not found. Please run the build step.</h1>"

@app.get("/api/events")
async def get_events():
    """Fetch Saturday events in Bangalore"""
    events = MeetupTool.fetch_bangalore_events()
    return {"events": events}

def main():
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 VSP Event Planner starting on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
