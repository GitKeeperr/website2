@echo off
cd /d "%~dp0"
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg was not found. Install FFmpeg and add it to PATH.
  echo Recommended: winget install Gyan.FFmpeg
  pause
  exit /b 1
)
if not exist .venv (py -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
start "" http://127.0.0.1:8765
python app.py
pause
