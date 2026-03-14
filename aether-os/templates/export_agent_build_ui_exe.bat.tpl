@echo off
setlocal

title Build UI __AGENT_NAME__
cd /d "%~dp0"

pip install pyinstaller uvicorn fastapi pydantic --quiet
pyinstaller --onefile --name "__SAFE_NAME___UI" --add-data "index.html;." --add-data "agent_profile.json;." gui_launcher.py

if %errorlevel%==0 (
  echo Build successful: dist\__SAFE_NAME___UI.exe
) else (
  echo Build failed.
)
pause
