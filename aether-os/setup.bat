@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title AetheerAI -- An AI Master!! Setup

:: ===========================================================================
::  AetheerAI -- An AI Master!!  |  Setup v1.0  |  Created by Tecbunny
:: ===========================================================================
::
::  This installer:
::   [1] Verifies Python 3.10+ is available
::   [2] Asks where to install  (default: %LOCALAPPDATA%\AetheerAI)
::   [3] Copies all source files (excludes caches / build artefacts)
::   [4] Creates a Python virtual environment in <install>\venv\
::   [5] Installs all dependencies listed in requirements.txt
::   [6] Copies .env.example -> .env  (first run only)
::   [7] Writes a venv-aware Launch_AetheerAI.bat into the install directory
::   [8] Creates a Desktop shortcut and a Start Menu entry
::   [9] Registers with Windows Add/Remove Programs
::  [10] Writes an Uninstall.bat inside the install directory
::  [11] Optionally launches AetheerAI immediately
::
:: ===========================================================================

set "SRC=%~dp0"
if "!SRC:~-1!"=="\" set "SRC=!SRC:~0,-1!"

color 0B
call :step_banner       || goto :install_failed
call :step_python       || goto :install_failed
call :step_dir
call :step_copy         || goto :install_failed
call :step_venv         || goto :install_failed
call :step_deps         || goto :install_failed
call :step_env
call :step_launcher
call :step_shortcuts
call :step_registry
call :step_uninstaller
call :step_done
goto :end

:: ===========================================================================
:step_banner
cls
echo.
echo  +================================================================+
echo  ^|                                                                ^|
echo  ^|      AetheerAI  --  An AI Master^^!^^!                           ^|
echo  ^|      Setup Wizard  v1.0   ^|   Created by Tecbunny             ^|
echo  ^|                                                                ^|
echo  +================================================================+
echo.
echo    Welcome^^!  This wizard installs AetheerAI as a Python source-
echo    code installation with a self-contained virtual environment.
echo.
echo    Requirements:
echo      - Python 3.10 or newer      https://www.python.org/downloads/
echo      - Internet access            (to download pip packages)
echo.
echo    Press any key to begin, or Ctrl+C to cancel.
pause >nul
exit /b 0

:: ===========================================================================
:step_python
echo.
echo  ── [Step 1 / 8]  Checking Python ──────────────────────────────────────
echo.
set "PY="

where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do (
        set "PYVER=%%V"
        set "PY=python"
    )
    goto :python_found
)

where py >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2" %%V in ('py --version 2^>^&1') do (
        set "PYVER=%%V"
        set "PY=py"
    )
    goto :python_found
)

color 0C
echo    [ERROR]  Python was not found on this system.
echo.
echo    Install Python 3.10+ from:
echo      https://www.python.org/downloads/
echo.
echo    IMPORTANT: During installation, tick "Add Python to PATH".
echo    Then re-run this setup.bat.
echo.
pause
exit /b 1

:python_found
echo    Found:  Python !PYVER!  (using: !PY!)

:: Warn if below 3.10
for /f "tokens=1,2 delims=." %%A in ("!PYVER!") do (
    set "_MAJOR=%%A"
    set "_MINOR=%%B"
)
if !_MAJOR! lss 3 goto :python_old_warn
if !_MAJOR!==3 if !_MINOR! lss 10 goto :python_old_warn
echo    Status: OK  (3.10+ required)
exit /b 0

:python_old_warn
color 0E
echo    WARNING: Python !PYVER! detected (3.10+ recommended).
echo             Proceeding anyway -- some features may not work correctly.
color 0B
exit /b 0

:: ===========================================================================
:step_dir
echo.
echo  ── [Step 2 / 8]  Installation Directory ───────────────────────────────
echo.
set "INSTALL_DIR=%LOCALAPPDATA%\AetheerAI"
set /p "_D=   Directory [!INSTALL_DIR!]: "
if not "!_D!"=="" set "INSTALL_DIR=!_D!"
if "!INSTALL_DIR:~-1!"=="\" set "INSTALL_DIR=!INSTALL_DIR:~0,-1!"
echo.
echo    Installing to: !INSTALL_DIR!
echo.
choice /c YN /m "   Confirm this directory?"
if errorlevel 2 goto :step_dir
exit /b 0

:: ===========================================================================
:step_copy
echo.
echo  ── [Step 3 / 8]  Copying source files ─────────────────────────────────
if not exist "!INSTALL_DIR!" (
    mkdir "!INSTALL_DIR!" 2>nul
    if errorlevel 1 (
        echo    [ERROR]  Cannot create: !INSTALL_DIR!
        exit /b 1
    )
)

robocopy "!SRC!" "!INSTALL_DIR!" /E ^
    /XD __pycache__ dist exports .git .vscode installer venv ^
    /XF *.pyc *.log setup.bat ^
    /NFL /NDL /NJH /NJS /NC /NS >nul

:: Robocopy exit codes 0-7 mean success (8+ = failure)
if !errorlevel! geq 8 (
    echo    [ERROR]  File copy failed  (robocopy code !errorlevel!).
    exit /b 1
)
echo    All source files copied to: !INSTALL_DIR!
exit /b 0

:: ===========================================================================
:step_venv
echo.
echo  ── [Step 4 / 8]  Creating virtual environment ─────────────────────────
set "VENV_PY=!INSTALL_DIR!\venv\Scripts\python.exe"
set "VENV_PIP=!INSTALL_DIR!\venv\Scripts\pip.exe"

if exist "!VENV_PY!" (
    echo    Existing virtual environment found -- skipping creation.
    exit /b 0
)

!PY! -m venv "!INSTALL_DIR!\venv"
if errorlevel 1 (
    echo    [ERROR]  Failed to create virtual environment.
    exit /b 1
)
echo    Virtual environment created.
exit /b 0

:: ===========================================================================
:step_deps
echo.
echo  ── [Step 5 / 8]  Installing dependencies ──────────────────────────────
echo    This may take 2-5 minutes depending on your connection. Please wait...
echo.
"!VENV_PIP!" install --upgrade pip --quiet
"!VENV_PIP!" install -r "!INSTALL_DIR!\requirements.txt"
if errorlevel 1 (
    echo.
    echo    [ERROR]  Dependency installation failed.
    echo             Check your internet connection and try again.
    exit /b 1
)
echo.
echo    All dependencies installed successfully.
exit /b 0

:: ===========================================================================
:step_env
echo.
echo  ── [Step 6 / 8]  Environment configuration ────────────────────────────
if not exist "!INSTALL_DIR!\.env" (
    if exist "!INSTALL_DIR!\.env.example" (
        copy /y "!INSTALL_DIR!\.env.example" "!INSTALL_DIR!\.env" >nul
        echo    Created .env from template.
        echo    Open the file below to add your AI provider API keys:
        echo      !INSTALL_DIR!\.env
    ) else (
        echo    No .env.example found; please create .env manually.
    )
) else (
    echo    .env already exists -- existing configuration preserved.
)
exit /b 0

:: ===========================================================================
:step_launcher
:: Write a venv-aware launcher batch file using disabledelayedexpansion
:: so that special chars (!, %) are output literally.
set "LAUNCHER=!INSTALL_DIR!\Launch_AetheerAI.bat"
setlocal disabledelayedexpansion
(
    echo @echo off
    echo title AetheerAI -- An AI Master
    echo color 0B
    echo cd /d "%INSTALL_DIR%"
    echo call "%INSTALL_DIR%\venv\Scripts\activate.bat"
    echo echo.
    echo echo  Starting AetheerAI -- An AI Master^^!^^!  ...
    echo echo  If your browser does not open automatically, visit:
    echo echo    http://localhost:8501
    echo echo.
    echo python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
    echo pause
) > "%INSTALL_DIR%\Launch_AetheerAI.bat"
endlocal
exit /b 0

:: ===========================================================================
:step_shortcuts
echo.
echo  ── [Step 7 / 8]  Creating shortcuts ───────────────────────────────────

:: Write a temp PowerShell script that creates both shortcuts
set "PS1=%TEMP%\ae_shortcuts_%RANDOM%.ps1"
setlocal disabledelayedexpansion
(
    echo $ws  = New-Object -ComObject WScript.Shell
    echo $dst = "$env:USERPROFILE\Desktop\AetheerAI.lnk"
    echo $s   = $ws.CreateShortcut($dst)
    echo $s.TargetPath      = "%INSTALL_DIR%\Launch_AetheerAI.bat"
    echo $s.WorkingDirectory = "%INSTALL_DIR%"
    echo $s.Description      = "AetheerAI -- An AI Master!!"
    echo $s.Save()
    echo $smDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\AetheerAI"
    echo if (-not (Test-Path $smDir)) { New-Item -ItemType Directory -Path $smDir | Out-Null }
    echo $s2 = $ws.CreateShortcut("$smDir\AetheerAI.lnk")
    echo $s2.TargetPath      = "%INSTALL_DIR%\Launch_AetheerAI.bat"
    echo $s2.WorkingDirectory = "%INSTALL_DIR%"
    echo $s2.Description      = "AetheerAI -- An AI Master!!"
    echo $s2.Save()
    echo Write-Host "  Shortcuts created."
) > "%TEMP%\ae_shortcuts_%RANDOM%.ps1"
endlocal

:: Re-capture PS1 path (endlocal clears local vars, use %TEMP% directly)
for %%F in ("%TEMP%\ae_shortcuts_*.ps1") do (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%%F" 2>nul
    del /f /q "%%F" >nul 2>&1
)

echo    Desktop shortcut:   %USERPROFILE%\Desktop\AetheerAI.lnk
echo    Start Menu entry:   Start ^> AetheerAI
exit /b 0

:: ===========================================================================
:step_registry
echo.
echo  ── [Step 8 / 8]  Registering with Windows ─────────────────────────────
set "UREG=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AetheerAI"
reg add "!UREG!" /v "DisplayName"     /t REG_SZ    /d "AetheerAI -- An AI Master!!" /f >nul
reg add "!UREG!" /v "Publisher"       /t REG_SZ    /d "Tecbunny"                    /f >nul
reg add "!UREG!" /v "DisplayVersion"  /t REG_SZ    /d "1.0.0"                       /f >nul
reg add "!UREG!" /v "InstallLocation" /t REG_SZ    /d "!INSTALL_DIR!"               /f >nul
reg add "!UREG!" /v "UninstallString" /t REG_SZ    /d "!INSTALL_DIR!\Uninstall.bat" /f >nul
reg add "!UREG!" /v "NoModify"        /t REG_DWORD /d 1                             /f >nul
reg add "!UREG!" /v "NoRepair"        /t REG_DWORD /d 1                             /f >nul
echo    Registered in Settings ^> Apps ^> Installed Apps.
exit /b 0

:: ===========================================================================
:step_uninstaller
:: Write Uninstall.bat using disabledelayedexpansion so %% and ! are literal
setlocal disabledelayedexpansion
(
    echo @echo off
    echo setlocal enabledelayedexpansion
    echo title AetheerAI Uninstaller
    echo color 0C
    echo echo.
    echo echo  +============================================================+
    echo echo  ^|    AetheerAI  Uninstaller   ^|   Created by Tecbunny       ^|
    echo echo  +============================================================+
    echo echo.
    echo echo  Installation directory: %INSTALL_DIR%
    echo echo.
    echo choice /c YN /m "  Remove AetheerAI completely?"
    echo if errorlevel 2 exit /b 0
    echo echo.
    echo echo  Removing shortcuts...
    echo del /f /q "%%USERPROFILE%%\Desktop\AetheerAI.lnk"           2^>nul
    echo rmdir /s /q "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\AetheerAI" 2^>nul
    echo echo  Removing registry entry...
    echo reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AetheerAI" /f 2^>nul
    echo echo  Scheduling removal of installation folder...
    echo echo @timeout /t 3 /nobreak ^>nul ^& rmdir /s /q "%INSTALL_DIR%" ^& del /f /q "%%TEMP%%\ae_del.bat" > "%%TEMP%%\ae_del.bat"
    echo start /b "" "%%TEMP%%\ae_del.bat"
    echo echo.
    echo echo  AetheerAI has been removed. The install folder will disappear
    echo echo  within a few seconds.
    echo echo.
    echo pause
) > "%INSTALL_DIR%\Uninstall.bat"
endlocal
exit /b 0

:: ===========================================================================
:step_done
color 0A
echo.
echo  +====================================================================+
echo  ^|                                                                    ^|
echo  ^|   AetheerAI installed successfully^^!    Created by Tecbunny        ^|
echo  ^|                                                                    ^|
echo  +====================================================================+
echo  ^|                                                                    ^|
echo  ^|   Location:   !INSTALL_DIR!
echo  ^|   Launch:     Desktop ^> AetheerAI                                 ^|
echo  ^|               Start ^> AetheerAI                                   ^|
echo  ^|   Config:     Edit .env to add your AI provider API key            ^|
echo  ^|   Uninstall:  Settings ^> Apps OR run Uninstall.bat                ^|
echo  ^|                                                                    ^|
echo  +====================================================================+
echo.
choice /c YN /m "  Launch AetheerAI now?"
if errorlevel 2 goto :end
start "" "!LAUNCHER!"
goto :end

:: ===========================================================================
:install_failed
color 0C
echo.
echo  +====================================================================+
echo  ^|   Setup failed. Please fix the error above and re-run setup.bat.  ^|
echo  +====================================================================+
echo.
pause

:end
endlocal
