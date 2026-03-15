@echo off
:: ================================================================
:: Build  AetheerAI -- An AI Master!!  --  Standalone Windows .exe
:: ================================================================
:: Output:  dist\AetheerAI_Master.exe
::
:: Double-clicking the .exe:
::   - Shows a welcome splash window
::   - Starts the Streamlit dashboard silently (no terminal)
::   - Opens the browser automatically
::   - Shows a small "AetheerAI is running" window when ready
::
:: Requirements: Python 3.10+ on PATH
:: First run takes 2-5 minutes (PyInstaller compiles everything)
:: ================================================================
title Build AetheerAI Master EXE
color 0B
cd /d "%~dp0"

echo.
echo  ============================================================
echo    AetheerAI -- An AI Master!!  --  Build Launcher
echo  ============================================================
echo.
echo  Installing / updating PyInstaller and Streamlit...
pip install pyinstaller streamlit --quiet
echo.
echo  Building AetheerAI_Master.exe  (please wait)...
echo.

:: Auto-detect Streamlit package location
for /f "delims=" %%i in ('python -c "import streamlit, os; print(os.path.dirname(streamlit.__file__))"') do set STREAMLIT_DIR=%%i
echo  Streamlit found at: %STREAMLIT_DIR%
echo.

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "AetheerAI_Master" ^
    --add-data "%STREAMLIT_DIR%\static;streamlit\static" ^
    --add-data "%STREAMLIT_DIR%\runtime;streamlit\runtime" ^
    --add-data "%STREAMLIT_DIR%\components;streamlit\components" ^
    --add-data "app.py;." ^
    --add-data "agents;agents" ^
    --add-data "ai;ai" ^
    --add-data "cli;cli" ^
    --add-data "core;core" ^
    --add-data "factory;factory" ^
    --add-data "memory;memory" ^
    --add-data "registry;registry" ^
    --add-data "security;security" ^
    --add-data "skills;skills" ^
    --add-data "tools;tools" ^
    --add-data "workspace;workspace" ^
    --add-data "agent_output;agent_output" ^
    --add-data "memory\memory_store.json;memory" ^
    --add-data "registry\registry_store.json;registry" ^
    --hidden-import streamlit ^
    --hidden-import chromadb ^
    --hidden-import chromadb.api ^
    --hidden-import openai ^
    --hidden-import anthropic ^
    --hidden-import yaml ^
    --hidden-import dotenv ^
    --hidden-import tiktoken ^
    --hidden-import tiktoken_ext ^
    --hidden-import tiktoken_ext.openai_public ^
    --hidden-import pydantic ^
    --hidden-import uvicorn ^
    --hidden-import requests ^
    --hidden-import bs4 ^
    --hidden-import pandas ^
    --hidden-import PIL ^
    --hidden-import cryptography ^
    --hidden-import threading ^
    --hidden-import concurrent.futures ^
    --collect-submodules chromadb ^
    --collect-submodules tiktoken_ext ^
    --collect-submodules streamlit ^
    launcher.py

:: NOTE: Enterprise tools require optional packages installed BEFORE building.
::   pip install PyGithub sqlalchemy playwright beautifulsoup4 markdownify
::   pip install boto3 google-cloud-storage kubernetes
::   pip install pylint black pypdf2 pillow

if %errorlevel%==0 (
    echo.
    echo  ============================================================
    echo   [OK]  Build complete!
    echo.
    echo   Your executable is at:
    echo     dist\AetheerAI_Master.exe
    echo.
    echo   IMPORTANT -- before running the .exe:
    echo     Copy your .env file into the dist\ folder.
    echo     It should contain your API key, e.g.:
    echo       GITHUB_TOKEN=ghp_your_token_here
    echo.
    echo   To run:
    echo     Double-click  dist\AetheerAI_Master.exe
    echo.
    echo   TIP: If Windows Defender shows a SmartScreen warning,
    echo        right-click the .exe ^> Properties ^> click Unblock
    echo  ============================================================
) else (
    echo.
    echo  [FAIL]  Build failed -- see output above for errors.
    echo.
    echo  Common fixes:
    echo    - Make sure you are running from the aether-os\ folder
    echo    - Run:  pip install -r requirements.txt
    echo    - Then retry this script
)
echo.
pause