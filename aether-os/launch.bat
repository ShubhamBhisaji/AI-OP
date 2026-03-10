@echo off
title Aether AI OS
color 0A
cd /d "%~dp0"

:: ── Find Python ──────────────────────────────────────────────────────────
set PY=
if exist "%~dp0.venv\Scripts\python.exe" (
    set PY="%~dp0.venv\Scripts\python.exe"
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PY="%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :run
)
where python >nul 2>&1
if %errorlevel%==0 (
    set PY=python
    goto :run
)

echo.
echo  [ERROR] Python not found.
echo  Install Python from https://www.python.org/downloads/
echo.
pause
exit /b 1

:run
echo.
echo  ============================================================
echo   Aether AI Operating System
echo   Starting with GitHub Models (Copilot Pro)...
echo  ============================================================
echo.

%PY% main.py %*

echo.
echo  ============================================================
echo   Aether OS exited.
echo  ============================================================
echo.
pause
