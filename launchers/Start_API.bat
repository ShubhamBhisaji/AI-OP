@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title AetheerAI -- REST API Server
cd /d "%~dp0..\AetheerAI"

:: ── Find Python ─────────────────────────────────────────────────────────────
set "PY="

python --version >nul 2>&1
if not errorlevel 1 ( set "PY=python" & goto :py_ok )

py -3 --version >nul 2>&1
if not errorlevel 1 ( set "PY=py -3" & goto :py_ok )

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" ( set "PY=%%D\python.exe" & goto :py_ok )
)

for /d %%D in ("%ProgramFiles%\Python3*") do (
    if exist "%%D\python.exe" ( set "PY=%%D\python.exe" & goto :py_ok )
)

echo.
echo  [ERROR] Python not found.
echo          Install Python 3.10+ from https://www.python.org/downloads/
echo          and tick "Add Python to PATH".
echo.
pause
exit /b 1

:py_ok
echo  Python : !PY!

:: ── Activate virtual environment if present ──────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo  Activating venv...
    call "venv\Scripts\activate.bat"
    set "PY=python"
)

:: ── Install dependencies silently if uvicorn is missing ──────────────────────
!PY! -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [INFO] Installing API dependencies -- please wait...
    !PY! -m pip install "fastapi>=0.111.0" "uvicorn[standard]>=0.29.0" "pydantic>=2.0.0" --quiet
    echo  Dependencies installed.
)

:: ── Read optional overrides from environment (or use defaults) ───────────────
if not defined AETHER_HOST set "AETHER_HOST=0.0.0.0"
if not defined AETHER_PORT set "AETHER_PORT=8000"

echo.
echo  ============================================================
echo   AetheerAI REST API + Web UI
echo   Listening : http://!AETHER_HOST!:!AETHER_PORT!
echo   Web UI    : http://localhost:!AETHER_PORT!/
echo   Docs      : http://localhost:!AETHER_PORT!/docs
echo   Health    : http://localhost:!AETHER_PORT!/api/health
echo   Press Ctrl+C to stop the server.
echo  ============================================================
echo.

:: ── Launch ───────────────────────────────────────────────────────────────────
!PY! start_api.py --host !AETHER_HOST! --port !AETHER_PORT!

echo.
echo  Server stopped.
pause
