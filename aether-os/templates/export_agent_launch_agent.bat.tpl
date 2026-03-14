@echo off
setlocal

title __AGENT_NAME__ - Agent Launcher
cd /d "%~dp0"

set PROVIDER=github
set MODEL=
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
    if /i "%%A"=="AETHER_DEFAULT_MODEL" set MODEL=%%B
  )
)

set PY=
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY (
  where python >nul 2>&1
  if %errorlevel%==0 (set PY=python)
)

if not defined PY (
  echo Python not found. Install from https://www.python.org/downloads/
  pause
  exit /b 1
)

if defined MODEL (
  %PY% run_agent.py --provider %PROVIDER% --model %MODEL% %*
) else (
  %PY% run_agent.py --provider %PROVIDER% %*
)
pause
