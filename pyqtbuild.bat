@echo off
title DoxyEdit PyQt6 Build
cd /d "%~dp0"
echo === Building DoxyEdit (PyQt6 variant) with Nuitka ===
echo.

:: Resolve the same Python used for the PySide6 build
where py >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=py
) else (
    set PYTHON=python
)

echo Using: %PYTHON%
echo.

echo Installing/updating build tools...
%PYTHON% -m pip install nuitka ordered-set zstandard PyQt6

echo.
echo Clearing scratch + previous PyQt dist...
if exist "build_pyqt_tmp" rmdir /s /q "build_pyqt_tmp"
if exist "dist\DoxyEdit-pyqt.exe" del /q "dist\DoxyEdit-pyqt.exe"

echo.
echo Codemodding PySide6 -^> PyQt6 into build_pyqt_tmp\ ...
%PYTHON% tools\build_pyqt.py
if errorlevel 1 (
    echo.
    echo [!] PyQt codemod / smoke test / build FAILED.
    echo     Inspect build_pyqt_tmp\ for any PySide6 idiom the regex missed.
    pause
    exit /b 1
)

echo.
echo === PyQt6 build complete! ===
echo Output: dist\DoxyEdit-pyqt.exe
echo Side-by-side PySide6 build: dist\DoxyEdit.exe
pause
