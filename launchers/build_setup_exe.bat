@echo off
setlocal EnableDelayedExpansion

rem ===========================================================================
rem  AetheerAI -- An AI Master!!
rem  FULL RELEASE BUILD  (build_setup_exe.bat)
rem
rem  Produces a single distributable installer:
rem     dist\AetheerAI_Setup_v1.0.0.exe
rem
rem  No Python required on the target machine -- everything is bundled.
rem
rem  USAGE:
rem    1.  (Optional) Install enterprise extras first -- see requirements.txt
rem    2.  Double-click this .bat  OR  run it in a command prompt
rem ===========================================================================

title AetheerAI Release Builder

echo.
echo  ============================================================
echo   AetheerAI -- An AI Master!!   ^|^|   Tecbunny Release Builder
echo  ============================================================
echo.

rem -- 0. Move to project root (same dir as this script) -------------------
 "OUTPUT_DIR=%~dp0..\output"
echo  [0] Output dir:   %OUTPUT_DIR%
echo  [0] Working in: %CD%
echo.

rem -- 1. Check Python ------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found in PATH.
    echo          Install Python 3.10+ and re-run.
    pause
    exit /b 1
)

rem -- 2. Ensure PyInstaller is available -----------------------------------
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo  [STEP] Installing PyInstaller...
    pip install pyinstaller
)

rem -- 3. Install core requirements (silent) --------------------------------
echo  [STEP] Installing Python requirements...
pip install -r requirements.txt --quiet

rem -- 4. Build the standalone EXE with PyInstaller -------------------------
echo.
echo  ============================================================
echo   STEP 1 / 2  --  Building AetheerAI_Master.exe
echo  ============================================================
echo.

:: Kill any running instance so Windows releases the file lock on the old EXE
taskkill /F /IM AetheerAI_Master.exe >nul 2>&1
timeout /t 2 /nobreak >nul 2>&1

:: Ensure runtime folders exist before PyInstaller scans them
if not exist "%OUTPUT_DIR%\agent_output" mkdir "%OUTPUT_DIR%\agent_output"

:: Auto-detect Streamlit package location
for /f "delims=" %%i in ('python -c "import streamlit, os; print(os.path.dirname(streamlit.__file__))"') do set STREAMLIT_DIR=%%i
echo  Streamlit found at: %STREAMLIT_DIR%
echo.

pip install pyinstaller streamlit opentelemetry-instrumentation backoff --quiet

pyinstaller ^
    --onefile ^
    --windowed ^

    --distpath "%OUTPUT_DIR%\dist" ^
    --workpath "%OUTPUT_DIR%\build" ^
    --specpath "%OUTPUT_DIR%" ^
    --add-data "%STREAMLIT_DIR%\static;streamlit\static" ^
    --add-data "%STREAMLIT_DIR%\runtime;streamlit\runtime" ^
    --add-data "%STREAMLIT_DIR%\components;streamlit\components" ^
    --add-data "app.py;." ^
    --add-data "agents;agents" ^
    --add-data "ai;ai" ^
    --add-data "cli;cli" ^
    --add-data "core;core" ^
    --add-data "evals;evals" ^
    --add-data "factory;factory" ^
    --add-data "memory;memory" ^
    --add-data "registry;registry" ^
    --add-data "security;security" ^
    --add-data "skills;skills" ^
    --add-data "templates;templates" ^
    --add-data "tools;tools" ^
    --add-data "utils;utils" ^
    --add-data "workspace;workspace" ^
    --add-data "%OUTPUT_DIR%\agent_output;agent_output" ^
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
    --hidden-import litellm ^
    --hidden-import litellm.main ^
    --hidden-import litellm.utils ^
    --hidden-import litellm.exceptions ^
    --hidden-import imaplib ^
    --hidden-import smtplib ^
    --hidden-import email ^
    --hidden-import email.mime.text ^
    --hidden-import email.mime.multipart ^
    --hidden-import email.mime.base ^
    --hidden-import email.encoders ^
    --hidden-import ssl ^
    --hidden-import socket ^
    --hidden-import ipaddress ^
    --hidden-import csv ^
    --hidden-import ast ^
    --hidden-import hashlib ^
    --hidden-import base64 ^
    --hidden-import difflib ^
    --hidden-import fnmatch ^
    --hidden-import stat ^
    --hidden-import sysconfig ^
    --hidden-import textwrap ^
    --hidden-import webbrowser ^
    --hidden-import shlex ^
    --hidden-import opentelemetry ^
    --hidden-import opentelemetry.instrumentation ^
    --hidden-import backoff ^
    --collect-submodules chromadb ^
    --collect-submodules tiktoken_ext ^
    --collect-submodules streamlit ^
    --collect-submodules litellm ^
    --copy-metadata streamlit ^
    launcher.py

if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller build FAILED.  Fix errors above and retry.
    pause
    exit /b 1
)

rem Verify the EXE was produced
if not exist "%OUTPUT_DIR%\dist\AetheerAI_Master.exe" (
    echo.
    echo  [ERROR] dist\AetheerAI_Master.exe was not produced.
    echo          Check build_main_exe.bat output for errors.
    pause
    exit /b 1
)

for %%F in ("%OUTPUT_DIR%\dist\AetheerAI_Master.exe") do set EXE_MB=%%~zF
set /a EXE_MB_APPROX=%EXE_MB% / 1048576
echo.
echo  [OK] dist\AetheerAI_Master.exe  (%EXE_MB_APPROX% MB)

rem -- 5. Find Inno Setup compiler ------------------------------------------
set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
) else (
    where ISCC >nul 2>&1
    if not errorlevel 1 ( set ISCC=ISCC )
)

if %ISCC%=="" (
    echo.
    echo  ============================================================
    echo   Inno Setup NOT found.
    echo  ============================================================
    echo.
    echo  Install Inno Setup 6 from: https://jrsoftware.org/isdl.php
    echo  Then re-run this script.
    echo.
    echo  The raw EXE is already usable:
    echo    dist\AetheerAI_Master.exe  (%EXE_MB_APPROX% MB)
    echo.
    pause
    exit /b 1
)

rem -- 6. Compile Inno Setup installer --------------------------------------
echo.
echo  ============================================================
echo   STEP 2 / 2  --  Building AetheerAI_Setup_v1.0.0.exe
echo  ============================================================
echo.

%ISCC% "installer\aetheerai_exe_setup.iss"
if errorlevel 1 (
    echo.
    echo  [ERROR] Inno Setup compilation FAILED.
    pause
    exit /b 1
)

rem -- 7. Report ------------------------------------------------------------
set SETUP_FILE=%OUTPUT_DIR%\dist\AetheerAI_Setup_v1.0.0.exe
if exist "%SETUP_FILE%" (
    for %%F in ("%SETUP_FILE%") do set SETUP_MB=%%~zF
    set /a SETUP_MB_APPROX=%SETUP_MB% / 1048576
    echo.
    echo  ============================================================
    echo   BUILD COMPLETE -- Release files ready:
    echo  ============================================================
    echo.
    echo    [1] dist\AetheerAI_Master.exe       (%EXE_MB_APPROX% MB)  ^<-- internal
    echo    [2] dist\AetheerAI_Setup_v1.0.0.exe (%SETUP_MB_APPROX% MB) ^<-- share this
    echo.
    echo   Distribute AetheerAI_Setup_v1.0.0.exe -- no Python needed.
    echo  ============================================================
) else (
    echo  [WARN] Setup EXE not found. Check Inno Setup output above.
)

echo.
pause