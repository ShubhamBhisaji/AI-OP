@echo off
setlocal

title __AGENT_NAME__ Dashboard
cd /d "%~dp0"

python --version >nul 2>&1 || (
  echo Python not found. Install Python 3.10+.
  pause
  exit /b 1
)

python -m streamlit --version >nul 2>&1 || python -m pip install streamlit --quiet
python -m streamlit run agent_app.py --server.headless false --browser.gatherUsageStats false
pause
