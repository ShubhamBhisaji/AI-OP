@echo off
title AetheerAI — An AI Master!! OS
cd /d "%~dp0..\AetheerAI"
set "PY=python"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo  ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
        echo         Alternatively, install the Python Launcher (py.exe).
        pause
        exit /b 1
    )
    set "PY=py -3"
)

:: Install Streamlit silently if missing
%PY% -m streamlit --version >nul 2>&1
if errorlevel 1 (
    %PY% -m pip install streamlit --quiet
)

:: Launch the silent GUI launcher (welcome splash + browser auto-open)
:: The terminal window closes immediately after starting the launcher
start "" %PY% launcher.py
exit
