@echo off
cd /d "%~dp0"

where pyw >nul 2>&1
if %errorlevel% == 0 (set PYTHON=pyw) else (set PYTHON=pythonw)

start "" %PYTHON% run.py %*
