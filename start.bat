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
echo  Installing dependencies...
echo.
%PYTHON% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo  [!] pip install failed. Check the errors above.
    pause
    exit /b 1
)

echo.
echo  Dependencies installed. Launching DoxyEdit...
echo.

%PYTHON% run.py %*

if errorlevel 1 (
    echo.
    echo  [!] DoxyEdit exited with an error.
    pause
)
