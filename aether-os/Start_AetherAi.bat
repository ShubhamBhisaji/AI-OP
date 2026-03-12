@echo off
title AetherAi Master OS
echo.
echo  ====================================================
echo   AetherAi-A Master AI  --  Master Dashboard
echo  ====================================================
echo.
echo  Booting Streamlit UI...
echo  (A browser window will open automatically)
echo.

:: Change to the script's own directory so imports resolve
cd /d "%~dp0"

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

:: Check Streamlit is installed — install silently if not
python -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo  Streamlit not found. Installing...
    python -m pip install streamlit --quiet
)

:: Launch the dashboard — opens browser automatically
python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false

pause
