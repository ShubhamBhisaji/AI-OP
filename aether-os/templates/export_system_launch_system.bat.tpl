@echo off
setlocal

title __SYSTEM_NAME__ - AI System
cd /d "%~dp0"

set PROVIDER=
set MODEL=
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
    if /i "%%A"=="AETHER_DEFAULT_MODEL" set MODEL=%%B
  )
)

where python >nul 2>&1
if %errorlevel% neq 0 (
  echo Python not found.
  pause
  exit /b 1
)

if defined MODEL (
  python run_system.py --provider %PROVIDER% --model %MODEL% %*
) else if defined PROVIDER (
  python run_system.py --provider %PROVIDER% %*
) else (
  python run_system.py %*
)
pause
