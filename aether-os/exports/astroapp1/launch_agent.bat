@echo off
title Aether Agent - astroapp1
color 0B
cd /d "%~dp0"
set PY=
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PY="%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :run
)
where python >nul 2>&1
if %errorlevel%==0 ( set PY=python & goto :run )
echo Python not found. Install from https://www.python.org/downloads/
pause & exit /b 1
:run
%PY% run_agent.py %*
pause
