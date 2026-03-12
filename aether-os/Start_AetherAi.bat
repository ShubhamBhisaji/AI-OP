@echo off
title AetheerAI — An AI Master!! OS
cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

:: Install Streamlit silently if missing
python -m streamlit --version >nul 2>&1
if errorlevel 1 (
    python -m pip install streamlit --quiet
)

:: Launch the silent GUI launcher (welcome splash + browser auto-open)
:: The terminal window closes immediately after starting the launcher
start "" pythonw launcher.py
exit
