@echo off
:: ================================================================
:: Build  AetherAi-A Master AI  —  Standalone Windows .exe
:: ================================================================
:: Output:  dist\AetherAi_MasterAI.exe
::
:: Requirements: Python 3.10+ on PATH
:: First run takes 2-5 minutes (PyInstaller compiles everything)
:: ================================================================
title Build  AetherAi-A Master AI
color 0B
cd /d "%~dp0"

echo.
echo  ============================================================
echo    AetherAi-A Master AI  —  Build Launcher
echo  ============================================================
echo.
echo  Installing / updating PyInstaller...
pip install pyinstaller --quiet
echo.
echo  Building AetherAi_MasterAI.exe  (please wait)...
echo.

pyinstaller ^
    --onefile ^
    --name "AetherAi_MasterAI" ^
    --add-data "agents;agents" ^
    --add-data "ai;ai" ^
    --add-data "cli;cli" ^
    --add-data "core;core" ^
    --add-data "factory;factory" ^
    --add-data "memory;memory" ^
    --add-data "registry;registry" ^
    --add-data "skills;skills" ^
    --add-data "tools;tools" ^
    --add-data "security;security" ^
    --add-data "utils;utils" ^
    --add-data "memory\memory_store.json;memory" ^
    --add-data "registry\registry_store.json;registry" ^
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
    --collect-submodules chromadb ^
    --collect-submodules tiktoken_ext ^
    --console ^
    main.py

if %errorlevel%==0 (
    echo.
    echo  ============================================================
    echo   [OK]  Build complete!
    echo.
    echo   Your executable is at:
    echo     dist\AetherAi_MasterAI.exe
    echo.
    echo   IMPORTANT — before running the .exe:
    echo     Copy your .env file into the same folder as the .exe
    echo     (the dist\ folder).  It should contain your API key, e.g.:
    echo       GITHUB_TOKEN=ghp_your_token_here
    echo.
    echo   To run:
    echo     Double-click  dist\AetherAi_MasterAI.exe
    echo     OR drag it anywhere and run it from there.
    echo.
    echo   TIP: If Windows Defender shows a SmartScreen warning,
    echo        right-click the .exe ^> Properties ^> click Unblock
    echo  ============================================================
) else (
    echo.
    echo  [FAIL]  Build failed — see output above for errors.
    echo.
    echo  Common fixes:
    echo    - Make sure you are running from the aether-os\ folder
    echo    - Run:  pip install -r requirements.txt
    echo    - Then retry this script
)
echo.
pause
