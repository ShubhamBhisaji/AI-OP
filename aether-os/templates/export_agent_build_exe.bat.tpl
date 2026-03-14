@echo off
setlocal

title Build __AGENT_NAME__
cd /d "%~dp0"
set NAME=__SAFE_NAME__

pip install pyinstaller --quiet
pyinstaller --onefile --name "%NAME%" --add-data "agent_profile.json;." --add-data ".env.example;." run_agent.py

if %errorlevel%==0 (
  echo Build successful: dist\%NAME%.exe
) else (
  echo Build failed.
)
pause
