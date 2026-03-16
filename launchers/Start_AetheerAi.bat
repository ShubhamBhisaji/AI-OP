@echo off
setlocal enabledelayedexpansion
title AetheerAI -- An AI Master!!
cd /d "%~dp0..\AetheerAI"

:: ── Find Python ─────────────────────────────────────────────────────────
set "PY="

python --version >nul 2>&1
if not errorlevel 1 ( set "PY=python" & goto :py_ok )

py -3 --version >nul 2>&1
if not errorlevel 1 ( set "PY=py -3" & goto :py_ok )

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
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
echo  Python: !PY!

:: ── Install Streamlit silently if missing ────────────────────────────────
!PY! -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo  Installing Streamlit -- please wait...
    !PY! -m pip install streamlit --quiet
)

:: ── Launch ───────────────────────────────────────────────────────────────
echo  Starting AetheerAI...
echo  If your browser does not open, visit:  http://localhost:8501
echo.

!PY! launcher.py
if errorlevel 1 (
    echo.
    echo  [ERROR] AetheerAI exited with an error. See details above.
    echo.
    pause
)
