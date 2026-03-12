@echo off
setlocal enabledelayedexpansion
title Build AetheerAI Setup Installer
color 0B

:: ===========================================================================
::  build_installer.bat
::  Compiles  installer\aetheerai_setup.iss  into  dist\AetheerAI_Setup.exe
::  using Inno Setup 6 (free — https://jrsoftware.org/isinfo.php)
::
::  Created by Tecbunny
:: ===========================================================================

cd /d "%~dp0"

echo.
echo  +================================================================+
echo  ^|   AetheerAI -- An AI Master^^!^^!   ^|   Build Setup Installer     ^|
echo  ^|   Created by Tecbunny                                         ^|
echo  +================================================================+
echo.

:: ── Locate Inno Setup Compiler (ISCC.exe) ─────────────────────────────────
set "ISCC="

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    goto :found
)
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    goto :found
)
if exist "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
    goto :found
)
if exist "%ProgramFiles%\Inno Setup 5\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 5\ISCC.exe"
    goto :found
)
where ISCC >nul 2>&1
if %errorlevel%==0 (
    set "ISCC=ISCC"
    goto :found
)

:: Not found
color 0C
echo  [ERROR]  Inno Setup was not found on this system.
echo.
echo  Download and install Inno Setup 6 (free) from:
echo    https://jrsoftware.org/isinfo.php
echo.
echo  After installing, re-run this script.
echo.
pause
exit /b 1

:found
echo  Inno Setup: !ISCC!
echo.

:: ── Ensure output directory exists ────────────────────────────────────────
if not exist "..\dist" mkdir "..\dist"

:: ── Compile ───────────────────────────────────────────────────────────────
echo  Compiling installer...
echo  Source:  installer\aetheerai_setup.iss
echo  Output:  dist\AetheerAI_Setup_v1.0.0.exe
echo.

"!ISCC!" /Q aetheerai_setup.iss

if !errorlevel!==0 (
    color 0A
    echo.
    echo  +================================================================+
    echo  ^|   BUILD SUCCESSFUL                                            ^|
    echo  ^|                                                                ^|
    echo  ^|   Output:  dist\AetheerAI_Setup_v1.0.0.exe                   ^|
    echo  ^|                                                                ^|
    echo  ^|   Distribute this single .exe file to end users.              ^|
    echo  ^|   Users double-click it to install AetheerAI.                 ^|
    echo  ^|                                                                ^|
    echo  ^|   NOTE: The installer requires Python to be installed on      ^|
    echo  ^|   the target machine. Users can get it from:                  ^|
    echo  ^|     https://www.python.org/downloads/                         ^|
    echo  ^|                                                                ^|
    echo  ^|   WINDOWS DEFENDER:  Unsigned .exe files may trigger          ^|
    echo  ^|   SmartScreen on first run. To dismiss:                       ^|
    echo  ^|     a) Right-click .exe ^> Properties ^> Unblock               ^|
    echo  ^|     b) Submit to Microsoft for analysis:                      ^|
    echo  ^|        https://www.microsoft.com/wdsi/filesubmission          ^|
    echo  ^|     c) Sign with a code-signing certificate (signtool.exe)    ^|
    echo  +================================================================+
) else (
    color 0C
    echo.
    echo  +================================================================+
    echo  ^|   BUILD FAILED — see output above for details.                ^|
    echo  +================================================================+
)

echo.
pause
