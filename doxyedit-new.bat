@echo off
title DoxyEdit — New Project
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel% == 0 (set PYTHON=py) else (set PYTHON=python)

set LOG=%~dp0doxyedit.log
echo [%date% %time%] Starting DoxyEdit (new project) > "%LOG%"

%PYTHON% run.py --new >> "%LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo  [!] DoxyEdit exited with an error.
    echo      Log saved to: %LOG%
    echo.
    type "%LOG%"
    echo.
    pause
)
