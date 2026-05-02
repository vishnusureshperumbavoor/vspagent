@echo off
cd /d "%~dp0"
echo 🚀 Starting VSP Saturday Event Planner Bot...

:: Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ❌ Virtual environment (venv) not found. Please create it first.
    pause
    exit /b
)

:: Activate venv and run bot
set PYTHONPATH=.
call venv\Scripts\activate.bat
python -m vspagent.bot

pause
