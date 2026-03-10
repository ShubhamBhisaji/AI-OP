@echo off
title Aether AI OS — Ollama (Local)
color 0B
cd /d "%~dp0"

:: ── Find Python ──────────────────────────────────────────────────────────
set PY=
if exist "%~dp0.venv\Scripts\python.exe" (
    set PY="%~dp0.venv\Scripts\python.exe"
    goto :find_ollama
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PY="%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :find_ollama
)
where python >nul 2>&1
if %errorlevel%==0 (
    set PY=python
    goto :find_ollama
)

echo.
echo  [ERROR] Python not found.
echo  Install Python from https://www.python.org/downloads/
echo.
pause
exit /b 1

:: ── Find Ollama ───────────────────────────────────────────────────────────
:find_ollama
set OLLAMA=
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set OLLAMA="%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    goto :check_ollama
)
where ollama >nul 2>&1
if %errorlevel%==0 (
    set OLLAMA=ollama
    goto :check_ollama
)

echo.
echo  [ERROR] Ollama not found.
echo  Download from https://ollama.com/download and install it.
echo.
pause
exit /b 1

:: ── Check Ollama is running, start if not ────────────────────────────────
:check_ollama
echo.
echo  ============================================================
echo   Aether AI OS — Ollama (Local AI)
echo  ============================================================
echo.

:: Check if ollama serve is already running by hitting the API
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo  Ollama server not running. Starting it now...
    start "Ollama Server" /min %OLLAMA% serve
    echo  Waiting for Ollama to start...
    timeout /t 4 /nobreak >nul
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  [ERROR] Ollama server failed to start.
        echo  Try running: ollama serve
        echo  in a separate terminal first.
        echo.
        pause
        exit /b 1
    )
    echo  Ollama server started.
    echo.
)

:: ── Pick model ────────────────────────────────────────────────────────────
set MODEL=llama3.2:1b

echo  Available locally-pulled models:
%OLLAMA% list
echo.
echo  Default model : %MODEL%
echo  To use a different model, run:
echo    launch_ollama.bat --model mistral
echo.

:: Allow --model override passed as argument
:parse_args
if "%~1"=="" goto :run
if /i "%~1"=="--model" (
    set MODEL=%~2
    shift
    shift
    goto :parse_args
)
shift
goto :parse_args

:run
echo  Starting Aether OS with Ollama / %MODEL%...
echo  ============================================================
echo.

%PY% main.py --provider ollama --model %MODEL%

echo.
echo  ============================================================
echo   Aether OS exited.
echo  ============================================================
echo.
pause
