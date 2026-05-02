@echo off
cd /d "%~dp0"

REM Prefer pythonw / pyw — windowless launchers, no console flash.
where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw run.py %*
    exit /b
)

where pyw >nul 2>&1
if %errorlevel% == 0 (
    start "" pyw run.py %*
    exit /b
)

REM Fallback to console Python (will briefly flash a console window).
where py >nul 2>&1
if %errorlevel% == 0 (
    start "" py run.py %*
    exit /b
)

where python >nul 2>&1
if %errorlevel% == 0 (
    start "" python run.py %*
    exit /b
)

echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
pause
