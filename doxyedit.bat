@echo off
title DoxyEdit
cd /d "%~dp0"

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

python run.py %*

if errorlevel 1 (
    echo.
    echo  [!] DoxyEdit exited with an error.
    echo  Make sure PySide6 and Pillow are installed:
    echo    pip install -r requirements.txt
    echo.
    pause
)
