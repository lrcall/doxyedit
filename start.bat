@echo off
title DoxyEdit Setup
cd /d "%~dp0"

echo.
echo  DoxyEdit — First-Run Setup
echo  ──────────────────────────
echo.

:: Prefer 'py' launcher (Windows Python Launcher), fall back to 'python'
where py >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=py
) else (
    where python >nul 2>&1
    if %errorlevel% == 0 (
        set PYTHON=python
    ) else (
        echo  [!] Python not found. Install Python 3.11+ from https://python.org
        pause
        exit /b 1
    )
)

echo  Using: %PYTHON%
echo.

set LOG=%~dp0doxyedit.log

echo [%date% %time%] First-run setup > "%LOG%"
echo [%date% %time%] Python: %PYTHON% >> "%LOG%"

echo  Installing dependencies...
echo.
%PYTHON% -m pip install -r requirements.txt >> "%LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo  [!] pip install failed. See log: %LOG%
    echo.
    type "%LOG%"
    echo.
    pause
    exit /b 1
)

echo  Dependencies installed. Launching DoxyEdit...
echo.

echo [%date% %time%] Launching app >> "%LOG%"
%PYTHON% run.py %* >> "%LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo  [!] DoxyEdit exited with an error.
    echo      Log saved to: %LOG%
    echo.
    type "%LOG%"
    echo.
    pause
)
