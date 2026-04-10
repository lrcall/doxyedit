@echo off
cd /d "%~dp0"

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

where pyw >nul 2>&1
if %errorlevel% == 0 (
    start "" pyw run.py %*
    exit /b
)

echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
pause
