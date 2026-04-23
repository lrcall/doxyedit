@echo off
title DoxyEdit Build
cd /d "%~dp0"
echo === Building DoxyEdit with Nuitka ===
echo.

:: Resolve the same Python that has PySide6 installed
:: Prefer 'py' launcher so we match start.bat; fall back to 'python'
where py >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=py
) else (
    set PYTHON=python
)

echo Using: %PYTHON%
echo.

echo Installing/updating build tools into the same Python...
%PYTHON% -m pip install nuitka ordered-set zstandard

echo.
echo Clearing Nuitka cache to ensure fresh build...
if exist "run.build" rmdir /s /q "run.build"
if exist "run.dist" rmdir /s /q "run.dist"
if exist "run.onefile-build" rmdir /s /q "run.onefile-build"

echo.
echo Building help file...
%PYTHON% build_help.py

echo.
echo Building...
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=doxyedit.ico ^
    --output-filename=DoxyEdit.exe ^
    --output-dir=dist ^
    --include-package=doxyedit ^
    --include-package=skia ^
    --include-module=PIL ^
    --include-module=psd_tools ^
    --include-module=numpy ^
    --include-module=markdown ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=scipy ^
    --nofollow-import-to=skimage ^
    --nofollow-import-to=sklearn ^
    --nofollow-import-to=pandas ^
    --nofollow-import-to=tkinter ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=test ^
    --nofollow-import-to=setuptools ^
    --nofollow-import-to=pip ^
    --nofollow-import-to=distutils ^
    --nofollow-import-to=pkg_resources ^
    --nofollow-import-to=docutils ^
    --nofollow-import-to=jinja2 ^
    --nofollow-import-to=pygments ^
    --nofollow-import-to=xmlrpc ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=lib2to3 ^
    --nofollow-import-to=ensurepip ^
    --nofollow-import-to=venv ^
    --nofollow-import-to=idlelib ^
    --nofollow-import-to=turtledemo ^
    run.py

if errorlevel 1 (
    echo.
    echo [!] Build FAILED.
    pause
    exit /b 1
)

echo.
echo === Build complete! ===
echo Output: dist\DoxyEdit.exe
pause
