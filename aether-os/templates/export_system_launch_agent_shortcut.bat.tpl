@echo off
setlocal

title __AGENT_NAME__ - __AGENT_ROLE__
cd /d "%~dp0"

set PROVIDER=
set MODEL=
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
    if /i "%%A"=="AETHER_DEFAULT_MODEL" set MODEL=%%B
  )
)

if defined MODEL (
  python run_system.py --agent __AGENT_NAME__ --provider %PROVIDER% --model %MODEL%
) else if defined PROVIDER (
  python run_system.py --agent __AGENT_NAME__ --provider %PROVIDER%
) else (
  python run_system.py --agent __AGENT_NAME__
)
pause
