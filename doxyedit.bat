@echo off
title DoxyEdit
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel% == 0 (set PYTHON=py) else (set PYTHON=python)

echo.
echo   ____                   _____    _ _ _
echo  ^|  _ \  ___  _  ___   _^| ____^|__^| ^(_) ^|_
echo  ^| ^| ^| ^|/ _ \^| ^|/ / ^| ^| ^|  _^| / _` ^| ^| __^|
echo  ^| ^|_^| ^| (_) ^|   ^<^| ^|_^| ^| ^|___^| (_^| ^| ^| ^|_
echo  ^|____/ \___/^|_^|\_\\__, ^|_____\__,_^|_^|\__^|
echo                    ^|___/
echo.
echo  Art Asset Manager
echo  ─────────────────
echo.

set LOG=%~dp0doxyedit.log

echo [%date% %time%] Starting DoxyEdit > "%LOG%"
echo [%date% %time%] Python: %PYTHON% >> "%LOG%"

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
